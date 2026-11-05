"""Loopback fakes for the SSO client tests: an IdP token endpoint and a team server. No network."""

from __future__ import annotations

import base64
import json
import threading
import urllib.parse
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

SENTINEL_TOKEN = "SENTINEL-ID-TOKEN-xyz"
SENTINEL_KEY = "SENTINEL-TEAM-KEY-abc"


def b64(d: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def make_id_token(nonce: str) -> str:
    return f"{b64({'alg': 'RS256'})}.{b64({'nonce': nonce, 'sub': 's', 'x': SENTINEL_TOKEN})}.sig"


class Fake:
    """One server playing both IdP and team server (different paths)."""

    def __init__(self) -> None:
        self.nonce_override: str | None = None
        self.exchange_calls: list[dict[str, Any]] = []
        self.token_calls: list[dict[str, str]] = []
        self.me_status = 200
        self.nonce = ""
        self.challenge = ""
        self.token_body: Any = None  # override the token endpoint response
        self.delete_status = 204
        self.deletes = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: object) -> None:
                pass

            def _send(self, status: int, body: dict[str, Any]) -> None:
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:
                if self.path == "/auth/config":
                    self._send(200, {"authorization_endpoint": outer.url + "/idp/authorize",
                                     "token_endpoint": outer.url + "/idp/token", "client_id": "client-1"})
                elif self.path == "/auth/me":
                    ok = self.headers.get("Authorization") == f"Bearer {SENTINEL_KEY}" and outer.me_status == 200
                    self._send(200 if ok else 401, {"email": "dev@example.com", "role": "member"} if ok else {})
                else:
                    self._send(404, {})

            def do_DELETE(self) -> None:
                if self.path == "/auth/me":
                    outer.deletes += 1
                    ok = outer.delete_status == 204 and self.headers.get("Authorization") == f"Bearer {SENTINEL_KEY}"
                    self.send_response(204 if ok else outer.delete_status if outer.delete_status != 204 else 401)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    self._send(404, {})

            def do_POST(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n).decode()
                if self.path == "/idp/token":
                    outer.token_calls.append(dict(urllib.parse.parse_qsl(raw)))
                    self._send(200, outer.token_body if outer.token_body is not None else
                               {"id_token": make_id_token(outer.nonce_override or outer.nonce), "access_token": "idp-at"})
                elif self.path == "/auth/exchange":
                    body = json.loads(raw)
                    outer.exchange_calls.append(body)
                    self._send(200, {"key": SENTINEL_KEY, "expires_at": "2030-01-01T00:00:00Z",
                                     "email": "dev@example.com", "role": "member"})
                else:
                    self._send(404, {})

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def browser(self, state_override: str | None = None, extra: str = "") -> Any:
        """open_browser stub: reads the login URL, then hits the loopback callback like the IdP redirect would."""

        def open_browser(url: str) -> bool:
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            self.nonce = q["nonce"]
            self.challenge = q["code_challenge"]
            cb = q["redirect_uri"] + "?" + urllib.parse.urlencode({"code": "the-code", "state": state_override or q["state"]}) + extra
            threading.Thread(target=lambda: urllib.request.urlopen(cb, timeout=10).read(), daemon=True).start()
            return True

        return open_browser


def fakes() -> Iterator[Fake]:
    f = Fake()
    try:
        yield f
    finally:
        f.close()
