"""The one outbound client the dashboard uses to reach the team server. The key stays here; reasons are fixed strings."""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Literal, NamedTuple

from seen_core import sync

TeamState = Literal["ok", "not_configured", "login_required", "unreachable", "unauthorized", "forbidden", "bad_response"]

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 10

REASONS: dict[TeamState, str] = {
    "not_configured": "Team sync is not set up. Set sync.server in the config on the host dashboard (run seen serve there).",
    "login_required": "Sign in with SSO to see team data.",
    "unreachable": "The team server could not be reached.",
    "unauthorized": "The team server did not accept the key. Sign in again, or check the key.",
    "forbidden": "Your team role does not allow this view.",
    "bad_response": "The team server sent a reply this dashboard could not read.",
}  # type: ignore[assignment]  # "ok" has no reason


class TeamResult(NamedTuple):
    state: TeamState
    reason: str | None
    body: Any


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a: Any, **k: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _open(req: urllib.request.Request) -> tuple[int, bytes]:
    """(status, body up to MAX_BYTES+1); status 0 on any network failure. A 3xx surfaces as its own status."""
    try:
        with _opener.open(req, timeout=TIMEOUT) as r:  # noqa: S310 (scheme checked by sync.server_url)
            return r.status, r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError):
        return 0, b""


def _fail(state: TeamState) -> TeamResult:
    return TeamResult(state, REASONS[state], None)


def fetch(path: str, query: dict[str, int] | None = None) -> TeamResult:
    if not path.startswith("/api/") or any(s in path for s in ("//", "..", "?", "#")):
        return _fail("bad_response")
    try:
        url = sync.server_url()
    except sync.SyncError:
        return _fail("not_configured")
    try:
        url, key = sync.server_and_key()
    except sync.SyncError:
        return _fail("login_required")
    if query:
        path += "?" + urllib.parse.urlencode({k: int(v) for k, v in query.items()})
    req = urllib.request.Request(url + path, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}, method="GET")
    status, raw = _open(req)
    if status == 401:
        return _fail("unauthorized")
    if status == 403:
        return _fail("forbidden")
    if status != 200:
        return _fail("unreachable")
    if len(raw) > MAX_BYTES:
        return _fail("bad_response")
    try:
        body = json.loads(raw)
    except ValueError:
        return _fail("bad_response")
    if not isinstance(body, dict):
        return _fail("bad_response")
    return TeamResult("ok", None, body)
