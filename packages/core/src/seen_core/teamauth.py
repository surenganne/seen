"""Team SSO login for the CLI: OIDC authorization code + PKCE (S256), public client, loopback redirect.

Flow: fetch {server}/auth/config, open the IdP in the browser, receive the code on a one-shot
listener at http://127.0.0.1:<ephemeral-port>/callback, trade it at the IdP token endpoint (verifier,
no client secret), then post only the id_token and nonce to {server}/auth/exchange. The team server is
the only signature validator; the client reads the id_token's nonce claim without verifying it, solely
to abort early on a mismatch. The minted key lives in ~/.seen/team_key (0600).

Microsoft Entra: loopback redirect URIs must be registered. Register `http://127.0.0.1/callback`
(Entra ignores the port for loopback addresses). Stdlib only. Nothing here prints a key or token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from . import config, paths, safeio, sync

_PAGE = b"<!doctype html><meta charset=utf-8><title>Seen</title><p>Signed in. You can close this tab and return to the terminal."


class LoginError(RuntimeError):
    """Messages are fixed text: never IdP-supplied, never a token."""


def pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def build_login_url(cfg: dict[str, str], state: str, nonce: str, challenge: str, redirect_uri: str) -> str:
    q = {"response_type": "code", "client_id": cfg["client_id"], "redirect_uri": redirect_uri, "scope": "openid email profile",
         "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"}
    return cfg["authorization_endpoint"] + ("&" if "?" in cfg["authorization_endpoint"] else "?") + urllib.parse.urlencode(q)


# ---- key file

def _key_file() -> Any:
    return paths.home() / "team_key"


def save_key(key: str) -> None:
    paths.ensure_dir(paths.home())
    safeio.write_text(_key_file(), key.strip() + "\n", paths.home())  # mkstemp creates 0600; rename keeps it


def load_key() -> str | None:
    try:
        return _key_file().read_text().strip() or None
    except OSError:
        return None


def clear_key() -> None:
    _key_file().unlink(missing_ok=True)


# ---- http helpers (no redirects: a redirect could carry the request off-origin)

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a: Any, **k: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _check_url(url: str) -> str:
    u = urllib.parse.urlparse(url)
    if u.scheme == "https" or (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1", "::1")):
        return url
    raise LoginError("The sign-in server must use https")


def _call(url: str, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: float = 15) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(_check_url(url), data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with _opener.open(req, timeout=timeout) as r:  # noqa: S310 (scheme checked above)
            body = json.loads(r.read() or b"{}")
            return r.status, body if isinstance(body, dict) else {}
    except urllib.error.HTTPError as e:
        return e.code, {}
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ValueError, OSError):
        return 0, {}


def _current_key() -> str | None:
    name = str(config.load()["sync"].get("api_key_env") or "SEEN_TEAM_API_KEY")
    return os.environ.get(name) or load_key()


def whoami() -> dict[str, str] | None:
    """{email, role} for the env or stored key; None when there is no key or the server refuses it."""
    url = sync.server_url()
    key = _current_key()
    if not key:
        return None
    status, body = _call(url + "/auth/me", headers={"Authorization": f"Bearer {key}"})
    if status == 0:
        raise LoginError("Could not reach the team server")
    return {"email": str(body.get("email", "")), "role": str(body.get("role", ""))} if status == 200 else None


def logout() -> str:
    """Best-effort server revoke of the stored key, then always delete the file.
    Returns "revoked", "local" (file removed, server not told) or "none" (no key file)."""
    key = load_key()
    if not key:
        clear_key()
        return "none"
    revoked = False
    try:
        req = urllib.request.Request(_check_url(sync.server_url() + "/auth/me"), headers={"Authorization": f"Bearer {key}"}, method="DELETE")
        with _opener.open(req, timeout=5) as r:  # noqa: S310 (scheme checked above)
            revoked = r.status == 204
    except Exception:  # noqa: BLE001 (best effort; never echo the cause)
        revoked = False
    clear_key()
    return "revoked" if revoked else "local"


# ---- login

def listen() -> HTTPServer:
    """One-shot listener: 127.0.0.1 only, ephemeral port. Never 0.0.0.0, never a name."""

    class H(BaseHTTPRequestHandler):
        timeout = 10  # a silent preconnect socket must not stall the login

        def log_message(self, *a: object) -> None:
            pass

        def do_GET(self) -> None:
            u = urllib.parse.urlparse(self.path)
            if u.path == "/callback":
                self.server.result = dict(urllib.parse.parse_qsl(u.query))  # type: ignore[attr-defined]
            self.send_response(200 if u.path == "/callback" else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(_PAGE) if u.path == "/callback" else 0))
            self.end_headers()
            if u.path == "/callback":
                self.wfile.write(_PAGE)  # fixed page: query params are never echoed

    srv = HTTPServer(("127.0.0.1", 0), H)
    srv.result = None  # type: ignore[attr-defined]
    return srv


def _nonce_of(id_token: str) -> str:
    try:
        seg = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
        return str(claims.get("nonce", "")) if isinstance(claims, dict) else ""
    except (IndexError, ValueError):
        return ""


def login(open_browser: Callable[[str], bool] = webbrowser.open, timeout_s: int = 300) -> dict[str, str]:
    try:
        return _login(open_browser, timeout_s)
    except (LoginError, sync.SyncError):
        raise
    except Exception:  # noqa: BLE001 (a fixed message: the cause may hold tokens in its frames)
        raise LoginError("Sign-in failed unexpectedly") from None


def _login(open_browser: Callable[[str], bool], timeout_s: int) -> dict[str, str]:
    server = sync.server_url()
    status, cfg = _call(server + "/auth/config")
    if status != 200 or not all(isinstance(cfg.get(k), str) and cfg[k] for k in ("authorization_endpoint", "token_endpoint", "client_id")):
        raise LoginError("Could not read the sign-in settings from the team server")
    _check_url(cfg["authorization_endpoint"])
    _check_url(cfg["token_endpoint"])
    verifier, challenge = pkce_pair()
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    srv = listen()
    try:
        redirect = f"http://127.0.0.1:{srv.server_address[1]}/callback"
        url = build_login_url(cfg, state, nonce, challenge, redirect)
        if not open_browser(url):
            print(f"Open this URL in your browser to sign in:\n{url}", file=sys.stderr)  # state/nonce/challenge are not secrets
        deadline = time.monotonic() + timeout_s
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise LoginError("Timed out waiting for the browser sign-in")
            srv.timeout = left
            srv.handle_request()
            cb: dict[str, str] | None = srv.result  # type: ignore[attr-defined]
            srv.result = None  # type: ignore[attr-defined]
            # only a callback carrying our state counts; anything else is ignored and we keep waiting
            if cb is not None and hmac.compare_digest(cb.get("state", "").encode(), state.encode()):
                break
    finally:
        srv.server_close()
    if "error" in cb:
        raise LoginError("The identity provider returned an error; sign-in cancelled")
    if not cb.get("code"):
        raise LoginError("The identity provider returned no code")
    form = urllib.parse.urlencode({"grant_type": "authorization_code", "code": cb["code"], "redirect_uri": redirect,
                                   "client_id": cfg["client_id"], "code_verifier": verifier}).encode()
    status, tok = _call(cfg["token_endpoint"], form, {"Content-Type": "application/x-www-form-urlencoded"})
    id_token = tok.get("id_token")
    if status != 200 or not isinstance(id_token, str):
        raise LoginError("The identity provider refused the sign-in")
    if not hmac.compare_digest(_nonce_of(id_token).encode(), nonce.encode()):
        raise LoginError("Sign-in nonce did not match; sign-in cancelled")
    status, ex = _call(server + "/auth/exchange", json.dumps({"id_token": id_token, "nonce": nonce}).encode(),
                       {"Content-Type": "application/json"})
    if status != 200 or not ex.get("key"):
        raise LoginError(f"The team server refused the sign-in (status {status})")
    save_key(str(ex["key"]))
    return {"email": str(ex.get("email", "")), "role": str(ex.get("role", "")), "expires_at": str(ex.get("expires_at", ""))}
