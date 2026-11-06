"""The one outbound client the dashboard uses to reach the team server. The key stays here; reasons are fixed strings."""

from __future__ import annotations

import http.client
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Literal, NamedTuple

from seen_core import sync

log = logging.getLogger(__name__)

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
}


class TeamResult(NamedTuple):
    state: TeamState
    reason: str | None
    body: Any


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a: Any, **k: Any) -> None:
        return None


def _opener() -> urllib.request.OpenerDirector:
    """Built per call so the no-proxy guarantee holds whatever the environment holds: the key goes straight to the server."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def _open(req: urllib.request.Request) -> tuple[int, bytes]:
    """(status, body up to MAX_BYTES+1); status 0 on any network failure. A 3xx surfaces as its own status."""
    try:
        with _opener().open(req, timeout=TIMEOUT) as r:  # noqa: S310 (scheme checked by sync.server_url)
            return r.status, r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        try:
            body = e.read(1025)  # a short error body: the public SSO probe tells "off" from "provider down" by it
        except OSError:
            body = b""
        e.close()
        return e.code, body
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError):
        return 0, b""


MAX_DEPTH = 64


def _too_deep(raw: bytes) -> bool:
    """True when brackets nest deeper than MAX_DEPTH. Checked before parsing: how far json recurses before it gives up
    depends on the Python version, and a hostile server must not be able to pick the outcome."""
    depth, in_str, esc = 0, False, False
    for ch in raw:
        if in_str:
            if esc:
                esc = False
            elif ch == 0x5C:
                esc = True
            elif ch == 0x22:
                in_str = False
        elif ch == 0x22:
            in_str = True
        elif ch in (0x5B, 0x7B):
            depth += 1
            if depth > MAX_DEPTH:
                return True
        elif ch in (0x5D, 0x7D):
            depth -= 1
    return False


def _fail(state: TeamState) -> TeamResult:
    return TeamResult(state, REASONS[state], None)


def fetch(path: str, query: dict[str, int] | None = None) -> TeamResult:
    if not path.startswith("/api/") or any(s in path for s in ("//", "..", "?", "#")):
        return _fail("bad_response")
    try:  # never use a message: some carry config or key text
        sync.server_url()
    except Exception as e:  # noqa: BLE001 (SyncError, bad TOML, anything)
        log.warning("team fetch failed: %s", type(e).__name__)  # type name only: messages can carry config or key text
        return _fail("not_configured")
    try:
        url, key = sync.server_and_key()
    except sync.SyncError:
        return _fail("login_required")
    except Exception as e:  # noqa: BLE001
        log.warning("team fetch failed: %s", type(e).__name__)
        return _fail("not_configured")
    key = key.strip()  # an env var often carries a trailing newline (the key file is already stripped)
    if not (key and key.isascii() and key.isprintable() and " " not in key):
        return _fail("unauthorized")  # unusable as a header value; no call, and nothing echoes it
    if query:
        path += "?" + urllib.parse.urlencode({k: int(v) for k, v in query.items()})
    req = urllib.request.Request(url + path, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}, method="GET")
    try:
        status, raw = _open(req)
    except Exception as e:  # noqa: BLE001 (messages can carry the key; keep no cause)
        log.warning("team fetch failed: %s", type(e).__name__)
        status, raw = 0, b""
    if status == 401:
        return _fail("unauthorized")
    if status == 403:
        return _fail("forbidden")
    if status != 200:
        return _fail("unreachable")
    if len(raw) > MAX_BYTES:
        return _fail("bad_response")
    if _too_deep(raw):
        return _fail("bad_response")
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError):
        return _fail("bad_response")
    if not isinstance(body, dict | list):
        return _fail("bad_response")
    return TeamResult("ok", None, body)


class PublicResult(NamedTuple):
    state: Literal["ok", "not_configured", "unreachable", "bad_response"]
    status: int
    body: Any


def fetch_public(path: str) -> PublicResult:
    """An unauthenticated GET of one fixed pre-auth path on the team server. No key is read or sent."""
    if path not in ("/auth/config",):
        return PublicResult("bad_response", 0, None)
    try:
        url = sync.server_url()
    except Exception as e:  # noqa: BLE001 (SyncError, bad TOML, anything)
        log.warning("team fetch failed: %s", type(e).__name__)
        return PublicResult("not_configured", 0, None)
    req = urllib.request.Request(url + path, headers={"Accept": "application/json"}, method="GET")
    try:
        status, raw = _open(req)
    except Exception as e:  # noqa: BLE001
        log.warning("team fetch failed: %s", type(e).__name__)
        status, raw = 0, b""
    if status == 0 or status == 429 or status >= 500 and status != 503:
        return PublicResult("unreachable", status, None)
    if len(raw) > MAX_BYTES:
        return PublicResult("bad_response", status, None)
    try:
        body = json.loads(raw) if raw else None
    except (ValueError, RecursionError):
        body = None
    return PublicResult("ok", status, body)
