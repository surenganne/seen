"""Dashboard SSO through the local server: the browser never sees the key, id_token, code or verifier."""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from seen_core import paths, teamauth
from tests.core.teamfakes import SENTINEL_KEY, SENTINEL_TOKEN, Fake, fakes

H = {"Host": "localhost", "X-Seen-Request": "1"}


@pytest.fixture
def fake(seen_home: Path) -> Iterator[Fake]:
    yield from fakes()


@pytest.fixture
def configured(fake: Fake, seeded: Path, monkeypatch: pytest.MonkeyPatch) -> Fake:
    paths.config_toml().write_text(f'[sync]\nenabled = true\nserver = "{fake.url}"\n')
    monkeypatch.delenv("SEEN_TEAM_API_KEY", raising=False)
    return fake


def start(client: TestClient, fake: Fake) -> dict[str, str]:
    r = client.post("/api/team/login", headers=H)
    assert r.status_code == 200
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.json()["url"]).query))
    fake.nonce = q["nonce"]
    return q


def cb(client: TestClient, **q: str) -> Any:
    return client.get("/api/team/callback", params=q, headers={"Host": "localhost"}, follow_redirects=False)


def test_login_needs_the_request_header(client: TestClient, configured: Fake) -> None:
    assert client.post("/api/team/login", headers={"Host": "localhost"}).status_code == 403
    assert client.post("/api/team/logout", headers={"Host": "localhost"}).status_code == 403


def test_login_url_points_at_the_idp_with_pkce(client: TestClient, configured: Fake) -> None:
    r = client.post("/api/team/login", headers=H)
    u = urllib.parse.urlparse(r.json()["url"])
    q = dict(urllib.parse.parse_qsl(u.query))
    assert r.json()["url"].startswith(configured.url + "/idp/authorize?")
    assert q["code_challenge_method"] == "S256" and q["client_id"] == "client-1"
    assert q["redirect_uri"].endswith("/api/team/callback") and q["redirect_uri"].startswith("http://127.0.0.1:")
    assert "code_verifier" not in q


def test_login_when_not_configured_gives_no_url(client: TestClient) -> None:
    assert client.post("/api/team/login", headers=H).json() == {"url": None, "reason": "not_configured"}


def test_login_when_server_unavailable_says_so(client: TestClient, configured: Fake) -> None:
    configured.close()
    assert client.post("/api/team/login", headers=H).json() == {"url": None, "reason": "unavailable"}


def test_pending_store_is_thread_safe() -> None:
    import threading
    import time

    from seen_local.team_login import Pending, PendingStore

    store, errors = PendingStore(), []

    def work(n: int) -> None:
        try:
            for i in range(400):
                store.put(f"{n}-{i}", Pending("v", "n", "r", time.monotonic() + (0.0001 if i % 2 else 60)))
                store.take(f"{n}-{i - 1}")
                store.prune()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == [] and len(store.entries) <= 20


def test_session_reports_not_configured_and_signed_out_without_key(client: TestClient, seeded: Path, configured: Fake,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real = teamauth._call
    monkeypatch.setattr(teamauth, "_call", lambda *a, **k: (calls.append(a[0]), real(*a, **k))[1])
    assert client.get("/api/team/session", headers=H).json() == {"state": "signed_out", "email": None, "role": None}
    assert calls == []  # no server call without a key


def test_session_not_configured(client: TestClient) -> None:
    assert client.get("/api/team/session", headers=H).json() == {"state": "not_configured", "email": None, "role": None}


def test_session_signed_in_then_rejected_then_unreachable(client: TestClient, configured: Fake) -> None:
    teamauth.save_key(SENTINEL_KEY)
    assert client.get("/api/team/session", headers=H).json() == {"state": "signed_in", "email": "dev@example.com", "role": "member"}
    configured.me_status = 401
    assert client.get("/api/team/session", headers=H).json() == {"state": "signed_out", "email": None, "role": None}
    configured.close()
    r = client.get("/api/team/session", headers=H)
    assert r.status_code == 200 and r.json()["state"] == "signed_out"


def test_full_login_saves_the_key_and_redirects_to_team(client: TestClient, configured: Fake) -> None:
    q = start(client, configured)
    r = cb(client, code="the-code", state=q["state"])
    assert r.status_code == 303 and r.headers["location"] == "/team"
    assert teamauth.load_key() == SENTINEL_KEY
    assert configured.token_calls[0]["code"] == "the-code" and configured.token_calls[0]["code_verifier"]
    assert configured.exchange_calls[0]["nonce"] == q["nonce"]
    assert client.get("/api/team/session", headers=H).json()["state"] == "signed_in"


def test_callback_rejects_unknown_replayed_and_expired_state(client: TestClient, configured: Fake,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real = teamauth._call
    monkeypatch.setattr(teamauth, "_call", lambda *a, **k: (calls.append(a[0]), real(*a, **k))[1])
    r = cb(client, code="c", state="never-issued")
    assert calls == []  # no outbound call for an unknown state
    assert r.status_code == 303 and r.headers["location"] == "/team" and teamauth.load_key() is None
    monkeypatch.setattr(teamauth, "_call", real)
    q = start(client, configured)
    assert cb(client, code="the-code", state=q["state"]).headers["location"] == "/team" and teamauth.load_key()
    teamauth.clear_key()
    assert cb(client, code="the-code", state=q["state"]).status_code == 303 and teamauth.load_key() is None  # replay
    q = start(client, configured)
    for entry in client.app.state.login_pending.entries.values():
        entry.expires -= 3600
    calls.clear()
    monkeypatch.setattr(teamauth, "_call", lambda *a, **k: (calls.append(a[0]), real(*a, **k))[1])
    assert cb(client, code="the-code", state=q["state"]).status_code == 303 and teamauth.load_key() is None
    assert calls == []  # no outbound call for an expired state


def test_callback_redirect_is_fixed(client: TestClient, configured: Fake) -> None:
    q = start(client, configured)
    for params in ({"code": "x", "state": "<script>alert(1)</script>"}, {"error": "evil", "state": q["state"]}, {},
                   {"code": "x" * 5000, "state": "//evil.example"}):
        r = cb(client, **params)
        assert r.status_code == 303 and r.headers["location"] == "/team" and r.content == b""
        assert "evil" not in str(r.headers) and "alert" not in str(r.headers)


def test_nonce_mismatch_does_not_sign_in(client: TestClient, configured: Fake) -> None:
    q = start(client, configured)
    configured.nonce_override = "other"
    assert cb(client, code="the-code", state=q["state"]).headers["location"] == "/team"
    assert teamauth.load_key() is None and not configured.exchange_calls


def test_pending_logins_are_capped(client: TestClient, configured: Fake) -> None:
    first = start(client, configured)
    for _ in range(25):
        start(client, configured)
    assert len(client.app.state.login_pending.entries) == 20
    configured.nonce_override = None
    assert cb(client, code="the-code", state=first["state"]).status_code == 303 and teamauth.load_key() is None


def test_logout_removes_key(client: TestClient, configured: Fake) -> None:
    teamauth.save_key(SENTINEL_KEY)
    r = client.post("/api/team/logout", headers=H)
    assert r.json() == {"state": "signed_out"} and teamauth.load_key() is None and configured.deletes == 1


def test_logout_of_an_already_invalid_key_is_audited_as_such(client: TestClient, configured: Fake,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    results: list[Any] = []
    import seen_local.team_login as tl
    monkeypatch.setattr(tl, "_audit", lambda *a, **k: results.append(k.get("result")), raising=False)
    teamauth.save_key(SENTINEL_KEY)
    configured.delete_status = 401
    r = client.post("/api/team/logout", headers=H)
    assert r.json() == {"state": "signed_out"} and teamauth.load_key() is None
    assert results == ["already_invalid"]


def test_no_secret_in_any_response_header_or_log(client: TestClient, configured: Fake, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    caplog.set_level("WARNING", logger="httpx")  # the test client's own request line, not the server's
    seen: list[Any] = []
    seen.append(client.get("/api/team/session", headers=H))
    q = start(client, configured)
    seen.append(client.post("/api/team/login", headers=H))
    seen.append(cb(client, code="the-code", state=q["state"]))
    seen.append(client.get("/api/team/session", headers=H))
    seen.append(cb(client, code="the-code", state=q["state"]))
    seen.append(client.post("/api/team/logout", headers=H))
    verifier = configured.token_calls[0]["code_verifier"]
    blob = " ".join(f"{r.text} {dict(r.headers)} {r.history}" for r in seen) + caplog.text
    for secret in (SENTINEL_KEY, SENTINEL_TOKEN, "the-code", verifier):
        assert secret not in blob


@pytest.fixture
def remote_client(seeded: Path) -> TestClient:
    from seen_local.app import create_app

    return TestClient(create_app(web_dist=None, remote=True), base_url="http://localhost")


def _record(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real = teamauth._call
    monkeypatch.setattr(teamauth, "_call", lambda *a, **k: (calls.append(a[0]), real(*a, **k))[1])
    return calls


def test_remote_dashboard_refuses_sign_in_without_any_outbound_call(remote_client: TestClient, configured: Fake,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record(monkeypatch)
    teamauth.save_key(SENTINEL_KEY)  # even with a key on disk the session is not shown
    assert remote_client.get("/api/team/session", headers=H).json() == {"state": "not_configured", "email": None, "role": None}
    assert remote_client.post("/api/team/login", headers=H).json() == {"url": None, "reason": "not_configured"}
    assert remote_client.app.state.login_pending.entries == {}  # type: ignore[attr-defined]
    assert calls == [] and configured.token_calls == [] and configured.exchange_calls == []


def test_remote_dashboard_callback_never_calls_out(remote_client: TestClient, configured: Fake,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    from seen_local.team_login import Pending

    # a pending login that is valid in every way: only the remote guard can stop the exchange
    remote_client.app.state.login_pending.put("st", Pending("v" * 43, "nonce-1", "http://127.0.0.1:1/api/team/callback", time.monotonic() + 60))  # type: ignore[attr-defined]
    calls = _record(monkeypatch)
    r = cb(remote_client, code="the-code", state="st")
    assert r.status_code == 303 and r.headers["location"] == "/team"
    assert calls == [] and configured.token_calls == [] and configured.exchange_calls == []
    assert teamauth._current_key() is None


def test_remote_dashboard_logout_is_a_no_op_and_cannot_revoke_the_owners_key(remote_client: TestClient, configured: Fake,
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record(monkeypatch)
    teamauth.save_key(SENTINEL_KEY)
    assert remote_client.post("/api/team/logout", headers=H).json() == {"state": "signed_out"}
    assert teamauth._current_key() == SENTINEL_KEY and calls == [] and configured.deletes == 0


def test_remote_dashboard_team_read_routes_never_call_out(remote_client: TestClient, configured: Fake,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_local import team

    fetched: list[str] = []
    real = team.fetch
    monkeypatch.setattr(team, "fetch", lambda *a, **k: (fetched.append(a[0]), real(*a, **k))[1])
    calls = _record(monkeypatch)
    monkeypatch.setenv("SEEN_TEAM_API_KEY", SENTINEL_KEY)
    for path in ("/api/team/projects", "/api/team/projects/p1/overview", "/api/team/projects/p1/members"):
        r = remote_client.get(path, headers=H)
        assert r.status_code == 200 and r.json()["state"] == "not_configured" and r.json()["reason"] == team.REASONS["not_configured"], path
    assert fetched == [] and calls == []


def test_local_dashboard_team_read_routes_still_fetch(client: TestClient, configured: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_local import team

    fetched: list[str] = []
    real = team.fetch
    monkeypatch.setattr(team, "fetch", lambda *a, **k: (fetched.append(a[0]), real(*a, **k))[1])
    monkeypatch.setenv("SEEN_TEAM_API_KEY", SENTINEL_KEY)
    for path in ("/api/team/projects", "/api/team/projects/p1/overview", "/api/team/projects/p1/members"):
        assert client.get(path, headers=H).status_code == 200
    assert len(fetched) == 3


def test_remote_dashboard_cannot_change_team_sync_settings(remote_client: TestClient, seeded: Path) -> None:
    # sync.server decides where the owner's key goes: a network peer must not be able to point it elsewhere
    r = remote_client.put("/api/settings", json={"sync": {"server": "https://attacker.example", "enabled": True}}, headers=H)
    assert r.status_code == 403
    assert "attacker" not in paths.config_toml().read_text() if paths.config_toml().exists() else True
    assert remote_client.put("/api/settings", json={"pii": {"mode": "report"}}, headers=H).status_code == 200  # other settings unchanged
