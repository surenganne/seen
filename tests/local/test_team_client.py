"""The local server's only outbound client to the team server: states, no redirects, caps, no key in results."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from seen_core import paths, teamauth
from seen_local import team

KEY = "sentinel-" + "z" * 40


def cfg(url: str = "http://127.0.0.1:9") -> None:
    paths.home().mkdir(parents=True, exist_ok=True)
    paths.config_toml().write_text(f'[sync]\nenabled = true\nserver = "{url}"\n')


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    monkeypatch.delenv("SEEN_TEAM_API_KEY", raising=False)
    out: list[Any] = []
    monkeypatch.setattr(team, "_open", lambda req: (out.append(req), (200, b"{}"))[1])
    return out


def reply(monkeypatch: pytest.MonkeyPatch, status: int, body: bytes) -> list[Any]:
    seen: list[Any] = []
    monkeypatch.setattr(team, "_open", lambda req: (seen.append(req), (status, body))[1])
    return seen


def test_not_configured_without_server(seen_home: Path, calls: list[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEEN_TEAM_API_KEY", KEY)
    r = team.fetch("/api/x")
    assert r.state == "not_configured" and r.reason == team.REASONS["not_configured"] and not calls
    assert "seen serve" in team.REASONS["not_configured"] and "sync.server" in team.REASONS["not_configured"]


def test_login_required_without_key(seen_home: Path, calls: list[Any]) -> None:
    cfg()
    r = team.fetch("/api/x")
    assert r.state == "login_required" and r.reason == team.REASONS["login_required"] and not calls


def test_key_file_used_and_env_wins(seen_home: Path, calls: list[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    cfg()
    teamauth.save_key("file-" + "k" * 40)
    assert team.fetch("/api/x").state == "ok"
    assert calls[-1].get_header("Authorization") == "Bearer file-" + "k" * 40
    monkeypatch.setenv("SEEN_TEAM_API_KEY", KEY)
    team.fetch("/api/x")
    assert calls[-1].get_header("Authorization") == f"Bearer {KEY}"


def test_sends_bearer_and_returns_json(seen_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg()
    monkeypatch.setenv("SEEN_TEAM_API_KEY", KEY)
    seen = reply(monkeypatch, 200, b'{"a": 1}')
    r = team.fetch("/api/team/x", {"days": 7, "limit": 5})
    req = seen[0]
    assert (r.state, r.body, r.reason) == ("ok", {"a": 1}, None)
    assert req.get_header("Authorization") == f"Bearer {KEY}" and req.get_header("Accept") == "application/json"
    assert req.full_url == "http://127.0.0.1:9/api/team/x?days=7&limit=5"
    assert sorted(k.lower() for k in req.headers) == ["accept", "authorization"]


@pytest.mark.parametrize("status,state", [(401, "unauthorized"), (403, "forbidden"), (0, "unreachable"), (500, "unreachable"),
                                          (404, "unreachable"), (429, "unreachable"), (302, "unreachable")])
def test_status_mapping(seen_home: Path, monkeypatch: pytest.MonkeyPatch, status: int, state: str) -> None:
    cfg()
    monkeypatch.setenv("SEEN_TEAM_API_KEY", KEY)
    reply(monkeypatch, status, b'{"a": 1}')
    r = team.fetch("/api/x")
    assert r.state == state and r.reason == team.REASONS[state] and r.body is None  # type: ignore[index]
    assert KEY not in repr(r)


@pytest.mark.parametrize("body", [b"not json", b'"s"', b"5", b"null", b"true", b"\xff\xfe{}", b"{" + b" " * (2 * 1024 * 1024 + 1) + b"}"])
def test_bad_body_states(seen_home: Path, monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    cfg()
    monkeypatch.setenv("SEEN_TEAM_API_KEY", KEY)
    reply(monkeypatch, 200, body)
    r = team.fetch("/api/x")
    assert r.state == "bad_response" and r.reason == team.REASONS["bad_response"]


@pytest.mark.parametrize("raw,want", [(b"[1, 2]", [1, 2]), (b'[{"id": "p"}]', [{"id": "p"}]), (b'{"a": 1}', {"a": 1})])
def test_list_and_object_bodies_come_back_intact(seen_home: Path, monkeypatch: pytest.MonkeyPatch, raw: bytes, want: Any) -> None:
    cfg()
    monkeypatch.setenv("SEEN_TEAM_API_KEY", KEY)
    reply(monkeypatch, 200, raw)
    r = team.fetch("/api/x")
    assert r.state == "ok" and r.body == want


@pytest.mark.parametrize("path", ["x", "/other", "/api//x", "/api/../x", "/api/x?a=1", "/api/x#f"])
def test_bad_path_makes_no_call(seen_home: Path, monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    cfg()
    monkeypatch.setenv("SEEN_TEAM_API_KEY", KEY)
    seen = reply(monkeypatch, 200, b"{}")
    assert team.fetch(path).state == "bad_response" and not seen


def test_reasons_are_fixed_and_clean() -> None:
    assert set(team.REASONS) == {"not_configured", "login_required", "unreachable", "unauthorized", "forbidden", "bad_response"}
    for v in team.REASONS.values():
        assert KEY not in v and "http" not in v


def _server(handler: type[BaseHTTPRequestHandler]) -> HTTPServer:
    s = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def test_redirect_is_not_followed(seen_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hits: list[str] = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a: Any) -> None: ...

    second = _server(Target)

    class Redir(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{second.server_port}/api/x")
            self.end_headers()

        def log_message(self, *a: Any) -> None: ...

    first = _server(Redir)
    try:
        cfg(f"http://127.0.0.1:{first.server_port}")
        monkeypatch.setenv("SEEN_TEAM_API_KEY", KEY)
        r = team.fetch("/api/x")
    finally:
        first.shutdown()
        second.shutdown()
    assert r.state == "unreachable" and hits == []


def test_real_open_reads_json(seen_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"auth": self.headers.get("Authorization")}).encode())

        def log_message(self, *a: Any) -> None: ...

    s = _server(H)
    try:
        cfg(f"http://127.0.0.1:{s.server_port}")
        monkeypatch.setenv("SEEN_TEAM_API_KEY", KEY)
        r = team.fetch("/api/x")
    finally:
        s.shutdown()
    assert r.state == "ok" and r.body == {"auth": f"Bearer {KEY}"}
