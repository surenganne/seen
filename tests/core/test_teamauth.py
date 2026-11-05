import base64
import hashlib
import os
import stat
import urllib.parse
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from seen_core import paths, sync, teamauth
from tests.core.teamfakes import SENTINEL_KEY, SENTINEL_TOKEN, Fake, fakes


@pytest.fixture
def fake(seen_home: Path) -> Iterator[Fake]:
    yield from fakes()


@pytest.fixture
def configured(fake: Fake, seen_home: Path, monkeypatch: pytest.MonkeyPatch) -> Fake:
    paths.ensure_dir(seen_home)
    paths.config_toml().write_text(f'[sync]\nenabled = true\nserver = "{fake.url}"\n')
    monkeypatch.delenv("SEEN_TEAM_API_KEY", raising=False)
    return fake


def test_pkce_matches_rfc7636_appendix_b(monkeypatch: pytest.MonkeyPatch) -> None:
    octets = bytes([116, 24, 223, 180, 151, 153, 224, 37, 79, 250, 96, 125, 216, 173, 187, 186, 22, 212, 37, 77, 105, 214, 191, 240, 91, 88, 5, 88, 83, 132, 141, 121])
    monkeypatch.setattr(teamauth.secrets, "token_bytes", lambda n: octets)
    v, c = teamauth.pkce_pair()
    assert v == "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert c == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert c == base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


def test_build_login_url() -> None:
    u = teamauth.build_login_url({"authorization_endpoint": "https://idp.example/authorize", "client_id": "c1"},
                                 "st", "no", "ch", "http://127.0.0.1:5/callback")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(u).query))
    assert q["response_type"] == "code" and q["code_challenge_method"] == "S256" and q["scope"] == "openid email profile"
    assert (q["state"], q["nonce"], q["code_challenge"], q["client_id"]) == ("st", "no", "ch", "c1")


def test_key_file_is_0600_and_cleared_on_logout(seen_home: Path) -> None:
    assert teamauth.load_key() is None
    teamauth.save_key("k1")
    f = paths.home() / "team_key"
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
    assert teamauth.load_key() == "k1"
    f.write_text("  k2\n")
    assert teamauth.load_key() == "k2"
    teamauth.clear_key()
    teamauth.clear_key()
    assert teamauth.load_key() is None
    f.write_text("  \n")
    assert teamauth.load_key() is None


def test_login_happy_path(configured: Fake) -> None:
    r = teamauth.login(open_browser=configured.browser(), timeout_s=10)
    assert r == {"email": "dev@example.com", "role": "member", "expires_at": "2030-01-01T00:00:00Z"}
    assert teamauth.load_key() == SENTINEL_KEY
    t = configured.token_calls[0]
    assert t["grant_type"] == "authorization_code" and t["code"] == "the-code" and "client_secret" not in t
    s256 = base64.urlsafe_b64encode(hashlib.sha256(t["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert s256 == configured.challenge
    assert set(configured.exchange_calls[0]) == {"id_token", "nonce"}  # nothing else goes to the team server


def test_login_rejects_state_mismatch(configured: Fake) -> None:
    with pytest.raises(teamauth.LoginError):
        teamauth.login(open_browser=configured.browser(state_override="evil"), timeout_s=1)
    assert configured.token_calls == [] and configured.exchange_calls == [] and teamauth.load_key() is None


def test_wrong_state_does_not_end_login_a_later_right_one_does(configured: Fake) -> None:
    import threading
    import urllib.request

    def browser(url: str) -> bool:
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        configured.nonce, configured.challenge = q["nonce"], q["code_challenge"]

        def hit() -> None:
            urllib.request.urlopen(q["redirect_uri"] + "?code=x&state=evil", timeout=10).read()
            urllib.request.urlopen(q["redirect_uri"] + "?code=the-code&state=" + q["state"], timeout=10).read()

        threading.Thread(target=hit, daemon=True).start()
        return True

    assert teamauth.login(open_browser=browser, timeout_s=10)["email"] == "dev@example.com"
    assert [c["code"] for c in configured.token_calls] == ["the-code"]


def test_login_prints_url_to_stderr_when_browser_cannot_open(configured: Fake, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(teamauth.LoginError):
        teamauth.login(open_browser=lambda url: False, timeout_s=1)
    assert "/idp/authorize?" in capsys.readouterr().err


def test_non_dict_token_response_is_a_clean_login_error(configured: Fake) -> None:
    configured.token_body = [SENTINEL_TOKEN]
    with pytest.raises(teamauth.LoginError) as e:
        teamauth.login(open_browser=configured.browser(), timeout_s=10)
    assert SENTINEL_TOKEN not in str(e.value)


def test_logout_revokes_then_clears(configured: Fake) -> None:
    teamauth.save_key(SENTINEL_KEY)
    assert teamauth.logout() == "revoked"
    assert configured.deletes == 1 and teamauth.load_key() is None


def test_logout_401_means_the_key_was_already_invalid(configured: Fake) -> None:
    teamauth.save_key(SENTINEL_KEY)
    configured.delete_status = 401
    assert teamauth.logout() == "already_invalid" and teamauth.load_key() is None


def test_logout_clears_even_when_server_refuses_or_is_missing(configured: Fake, seen_home: Path) -> None:
    teamauth.save_key(SENTINEL_KEY)
    configured.delete_status = 403
    assert teamauth.logout() == "local"
    assert teamauth.load_key() is None
    teamauth.save_key(SENTINEL_KEY)
    paths.config_toml().write_text("[sync]\n")  # no server configured
    assert teamauth.logout() == "local" and teamauth.load_key() is None
    assert teamauth.logout() == "none"


def test_whoami_uses_env_key_first_and_reports_unreachable(configured: Fake, monkeypatch: pytest.MonkeyPatch, seen_home: Path) -> None:
    monkeypatch.setenv("SEEN_TEAM_API_KEY", SENTINEL_KEY)
    assert teamauth.whoami() == {"email": "dev@example.com", "role": "member"}
    monkeypatch.delenv("SEEN_TEAM_API_KEY")
    assert teamauth.whoami() is None
    teamauth.save_key(SENTINEL_KEY)
    configured.close()
    with pytest.raises(teamauth.LoginError, match="reach"):
        teamauth.whoami()


def test_login_rejects_nonce_mismatch(configured: Fake) -> None:
    configured.nonce_override = "other"
    with pytest.raises(teamauth.LoginError):
        teamauth.login(open_browser=configured.browser(), timeout_s=10)
    assert configured.exchange_calls == [] and teamauth.load_key() is None


def test_login_idp_error_param_aborts_without_echo(configured: Fake) -> None:
    def browser(url: str) -> bool:
        import threading
        import urllib.request

        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        cb = q["redirect_uri"] + "?" + urllib.parse.urlencode({"error": "SECRET-IDP-TEXT", "state": q["state"]})
        threading.Thread(target=lambda: urllib.request.urlopen(cb, timeout=10).read(), daemon=True).start()
        return True

    with pytest.raises(teamauth.LoginError) as e:
        teamauth.login(open_browser=browser, timeout_s=10)
    assert "SECRET-IDP-TEXT" not in str(e.value)


def test_login_times_out(configured: Fake) -> None:
    with pytest.raises(teamauth.LoginError, match="[Tt]imed out"):
        teamauth.login(open_browser=lambda url: True, timeout_s=1)


def test_listener_binds_loopback_only() -> None:
    srv = teamauth.listen()
    try:
        assert srv.server_address[0] == "127.0.0.1" and srv.server_address[1] > 0
    finally:
        srv.server_close()


def test_callback_page_is_static_and_never_echoes(configured: Fake) -> None:
    import threading
    import urllib.request

    seen: list[str] = []

    def browser(url: str) -> bool:
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        configured.nonce = q["nonce"]

        def hit() -> None:
            seen.append(urllib.request.urlopen(q["redirect_uri"] + "?code=c&state=" + q["state"] + "&x=ECHOME", timeout=10).read().decode())

        threading.Thread(target=hit, daemon=True).start()
        return True

    teamauth.login(open_browser=browser, timeout_s=10)
    import time
    time.sleep(0.2)
    assert seen and "ECHOME" not in seen[0]


def test_login_never_prints_key_or_token(configured: Fake, capsys: pytest.CaptureFixture[str]) -> None:
    teamauth.login(open_browser=configured.browser(), timeout_s=10)
    out = capsys.readouterr()
    for s in (SENTINEL_KEY, SENTINEL_TOKEN, "the-code", configured.token_calls[0]["code_verifier"]):
        assert s not in out.out + out.err


def test_login_refuses_http_non_loopback_server(seen_home: Path) -> None:
    paths.ensure_dir(seen_home)
    paths.config_toml().write_text('[sync]\nserver = "http://example.com"\n')
    with pytest.raises(sync.SyncError):
        teamauth.login(open_browser=lambda u: True, timeout_s=1)


def test_sync_falls_back_to_key_file(configured: Fake) -> None:
    teamauth.save_key("filekey")
    assert sync.server_and_key() == (configured.url, "filekey")


def test_env_key_wins_over_file(configured: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    teamauth.save_key("filekey")
    monkeypatch.setenv("SEEN_TEAM_API_KEY", "envkey")
    assert sync.server_and_key()[1] == "envkey"


def test_no_key_error_mentions_login(configured: Fake) -> None:
    with pytest.raises(sync.SyncError, match="seen team login"):
        sync.server_and_key()


def test_complete_never_leaks_an_unexpected_error(configured: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    def bad_save(key: str) -> None:
        raise RuntimeError(f"disk said {key} {SENTINEL_TOKEN}")

    monkeypatch.setattr(teamauth, "save_key", bad_save)
    cfg = teamauth.fetch_config(configured.url)
    configured.nonce = "n1"
    with pytest.raises(teamauth.LoginError) as e:
        teamauth.complete(configured.url, cfg, "c", "v", "n1", "http://127.0.0.1:1/cb")
    assert str(e.value) == "Sign-in failed unexpectedly" and e.value.__cause__ is None and e.value.__suppress_context__
    assert SENTINEL_KEY not in repr(e.value) and SENTINEL_TOKEN not in repr(e.value)


def test_callback_page_for_a_wrong_state_is_neutral() -> None:
    import threading
    import urllib.request

    srv = teamauth.listen("good-state")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}/callback"
        wrong = urllib.request.urlopen(base + "?code=c&state=bad", timeout=5).read().decode()
        missing = urllib.request.urlopen(base, timeout=5).read().decode()
        right = urllib.request.urlopen(base + "?code=c&state=good-state", timeout=5).read().decode()
    finally:
        srv.shutdown()
        srv.server_close()
    assert "Signed in" not in wrong and "Signed in" not in missing and "not valid" in wrong
    assert "Signed in" in right


def _serve(handler: type) -> Any:
    import threading
    from http.server import HTTPServer

    s = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def test_calls_ignore_proxy_environment(seen_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The team server and IdP are reached directly. A proxy variable pointing at a listener that records connections
    must never be dialled by _call (login), the revoke in logout, or whoami."""
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler

    dialled: list[int] = []
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    probe.listen(5)

    def accept() -> None:
        while True:
            try:
                c, _ = probe.accept()
            except OSError:
                return
            dialled.append(1)
            c.close()

    threading.Thread(target=accept, daemon=True).start()

    class H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok": 1}')

        do_DELETE = do_GET

        def log_message(self, *a: object) -> None: ...

    s = _serve(H)
    try:
        for v in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.setenv(v, f"http://127.0.0.1:{probe.getsockname()[1]}")
        monkeypatch.setenv("NO_PROXY", "")
        status, body = teamauth._call(f"http://127.0.0.1:{s.server_port}/x")
        paths.ensure_dir(seen_home)
        paths.config_toml().write_text(f'[sync]\nenabled = true\nserver = "http://127.0.0.1:{s.server_port}"\n')
        teamauth.save_key(SENTINEL_KEY)
        teamauth.logout()
    finally:
        s.shutdown()
        probe.close()
    assert (status, body) == (200, {"ok": 1}) and dialled == []


@pytest.mark.parametrize("lie", [True, False])
def test_call_stops_reading_at_the_cap(monkeypatch: pytest.MonkeyPatch, lie: bool) -> None:
    import http.client
    from http.server import BaseHTTPRequestHandler

    class H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            if lie:
                self.send_header("Content-Length", "10")
            self.end_headers()
            try:
                self.wfile.write(b'{"a": "' + b"x" * (3 * 1024 * 1024))
            except OSError:
                pass
            self.close_connection = True

        def log_message(self, *a: object) -> None: ...

    got = [0]
    real_read = http.client.HTTPResponse.read

    def counting(self: http.client.HTTPResponse, amt: int | None = None) -> bytes:
        data = real_read(self, amt)
        got[0] += len(data)
        return data

    monkeypatch.setattr(http.client.HTTPResponse, "read", counting)
    s = _serve(H)
    try:
        result = teamauth._call(f"http://127.0.0.1:{s.server_port}/x")
    finally:
        s.shutdown()
    assert result == (0, {})  # over the cap is a failure, not a truncated parse
    assert got[0] <= teamauth.MAX_BYTES + 1
    if not lie:
        assert got[0] == teamauth.MAX_BYTES + 1
