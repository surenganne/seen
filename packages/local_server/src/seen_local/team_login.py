"""Dashboard sign-in through the local server (SSO-3).

The browser only ever gets the IdP authorize URL and a redirect to /team. State, nonce and PKCE verifier live here in
memory; the code exchange, the team key and the id_token never leave this process.

Entra: register this exact redirect URI on the app registration: http://127.0.0.1:47821/api/team/callback
(port = the dashboard port; Entra ignores the port for loopback, but the path must match).
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from seen_core import audit, sync, teamauth
from seen_core.identity import user_id

from . import schemas as S

TTL_S = 600
MAX_PENDING = 20
DEFAULT_PORT = 47821
SIGNED_OUT = S.TeamSession(state="signed_out", email=None, role=None)


@dataclass
class Pending:
    verifier: str
    nonce: str
    redirect: str
    expires: float


class PendingStore:
    """In-memory, single use, 10-minute TTL, capped: the oldest entry is dropped so it cannot be filled."""

    def __init__(self) -> None:
        self.entries: dict[str, Pending] = {}

    def put(self, state: str, p: Pending) -> None:
        self.prune()
        while len(self.entries) >= MAX_PENDING:
            del self.entries[next(iter(self.entries))]
        self.entries[state] = p

    def take(self, state: str) -> Pending | None:
        self.prune()
        return self.entries.pop(state, None)

    def prune(self) -> None:
        now = time.monotonic()
        for k in [k for k, p in self.entries.items() if p.expires <= now]:
            del self.entries[k]


def _redirect_uri(request: Request) -> str:
    server = request.scope.get("server")
    port = server[1] if server and isinstance(server[1], int) and server[1] > 0 else DEFAULT_PORT
    return f"http://127.0.0.1:{port}/api/team/callback"


def _audit(type_: str, outcome: str, **detail: Any) -> None:
    audit.append([{"type": type_, "actor_kind": "user", "actor_id": user_id(), "outcome": outcome, "detail": detail}])


def _done() -> RedirectResponse:
    return RedirectResponse("/team", status_code=303)  # fixed target: nothing is ever reflected


def register(app: FastAPI) -> None:
    pending = app.state.login_pending = PendingStore()

    def server() -> str | None:
        try:
            return sync.server_url()
        except sync.SyncError:
            return None

    @app.get("/api/team/session", response_model=S.TeamSession)
    def session() -> S.TeamSession:
        if server() is None:
            return S.TeamSession(state="not_configured", email=None, role=None)
        if not teamauth._current_key():
            return SIGNED_OUT
        try:
            who = teamauth.whoami()
        except Exception:  # noqa: BLE001 (unreachable or odd server: never echo the cause)
            return SIGNED_OUT
        return S.TeamSession(state="signed_in", email=who["email"], role=who["role"]) if who else SIGNED_OUT

    @app.post("/api/team/login", response_model=S.TeamLoginOut)
    def login(request: Request) -> S.TeamLoginOut:
        srv = server()
        try:
            cfg = teamauth.fetch_config(srv) if srv else None
        except Exception:  # noqa: BLE001
            cfg = None
        if cfg is None:
            _audit("team.login_started", "failed")
            return S.TeamLoginOut(url=None)
        verifier, challenge = teamauth.pkce_pair()
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        redirect = _redirect_uri(request)
        pending.put(state, Pending(verifier, nonce, redirect, time.monotonic() + TTL_S))
        _audit("team.login_started", "ok")
        return S.TeamLoginOut(url=teamauth.build_login_url(cfg, state, nonce, challenge, redirect))

    @app.get("/api/team/callback", include_in_schema=False)
    def callback(code: str = "", state: str = "") -> RedirectResponse:
        p = pending.take(state)  # unknown, replayed or expired: nothing else happens, no outbound call
        if p is None or not code:
            return _done()
        try:
            srv = server()
            who = teamauth.complete(srv, teamauth.fetch_config(srv), code, p.verifier, p.nonce, p.redirect) if srv else None
            _audit("team.login", "ok" if who else "failed")
        except Exception:  # noqa: BLE001 (fixed outcome; the cause may hold tokens)
            _audit("team.login", "failed")
        return _done()

    @app.post("/api/team/logout", response_model=S.TeamLogoutOut)
    def logout() -> S.TeamLogoutOut:
        try:
            result = teamauth.logout()
        except Exception:  # noqa: BLE001
            teamauth.clear_key()
            result = "local"
        _audit("team.logout", "ok", result=result)
        return S.TeamLogoutOut(state="signed_out")

