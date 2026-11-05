import base64
import hashlib
import os
import stat
import urllib.parse
from collections.abc import Iterator
from pathlib import Path

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
    assert hashlib.sha256(t["code_verifier"].encode()).digest()
    assert set(configured.exchange_calls[0]) == {"id_token", "nonce"}  # nothing else goes to the team server


def test_login_rejects_state_mismatch(configured: Fake) -> None:
    with pytest.raises(teamauth.LoginError):
        teamauth.login(open_browser=configured.browser(state_override="evil"), timeout_s=10)
    assert configured.token_calls == [] and teamauth.load_key() is None


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
