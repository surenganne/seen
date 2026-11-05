from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seen_cli.main import app
from seen_core import paths, teamauth
from tests.core.teamfakes import SENTINEL_KEY, SENTINEL_TOKEN, Fake, fakes

cli = CliRunner()


@pytest.fixture
def configured(seen_home: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Fake]:
    monkeypatch.delenv("SEEN_TEAM_API_KEY", raising=False)
    for f in fakes():
        paths.ensure_dir(seen_home)
        paths.config_toml().write_text(f'[sync]\nenabled = true\nserver = "{f.url}"\n')
        yield f


def test_whoami_prints_email_and_role_only(configured: Fake) -> None:
    teamauth.save_key(SENTINEL_KEY)
    r = cli.invoke(app, ["team", "whoami"])
    assert r.exit_code == 0 and "dev@example.com" in r.output and "member" in r.output
    assert SENTINEL_KEY not in r.output


def test_whoami_not_signed_in_and_expired(configured: Fake) -> None:
    r = cli.invoke(app, ["team", "whoami"])
    assert r.exit_code == 1 and "seen team login" in r.output
    teamauth.save_key("stale")
    r = cli.invoke(app, ["team", "whoami"])
    assert r.exit_code == 1 and "seen team login" in r.output and "stale" not in r.output


def test_logout_messages(configured: Fake) -> None:
    teamauth.save_key(SENTINEL_KEY)
    r = cli.invoke(app, ["team", "logout"])
    assert r.exit_code == 0 and "revoked on the server" in r.output and teamauth.load_key() is None
    assert "Not signed in" in cli.invoke(app, ["team", "logout"]).output
    teamauth.save_key(SENTINEL_KEY)
    configured.delete_status = 403
    r = cli.invoke(app, ["team", "logout"])
    assert "Signed out locally" in r.output and "30 days" in r.output and teamauth.load_key() is None
    teamauth.save_key(SENTINEL_KEY)
    configured.delete_status = 401
    r = cli.invoke(app, ["team", "logout"])
    assert "Signed out. The key was already invalid on the server." in r.output and teamauth.load_key() is None


def test_whoami_unreachable_is_distinct(configured: Fake) -> None:
    teamauth.save_key(SENTINEL_KEY)
    configured.close()
    r = cli.invoke(app, ["team", "whoami"])
    assert r.exit_code == 1 and "reach" in r.output and "seen team login" not in r.output


def _no_secret_leak(r: object) -> None:
    out = getattr(r, "output", "")
    for s in (SENTINEL_KEY, SENTINEL_TOKEN, "the-code"):
        assert s not in out


def test_unexpected_error_in_login_leaks_nothing(configured: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    real = teamauth.login
    monkeypatch.setattr(teamauth, "login", lambda timeout_s=300: real(open_browser=configured.browser(), timeout_s=timeout_s))

    def boom(key: str) -> None:
        raise RuntimeError("disk " + key)

    monkeypatch.setattr(teamauth, "save_key", boom)
    r = cli.invoke(app, ["team", "login", "--timeout", "10"])
    assert r.exit_code == 1 and "Sign-in failed" in r.output
    _no_secret_leak(r)
    assert r.exception is None or isinstance(r.exception, SystemExit)


def test_typer_app_hides_locals() -> None:
    assert app.pretty_exceptions_show_locals is False


def test_login_command_output_has_no_secrets(configured: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    real = teamauth.login
    monkeypatch.setattr(teamauth, "login", lambda timeout_s=300: real(open_browser=configured.browser(), timeout_s=timeout_s))
    r = cli.invoke(app, ["team", "login", "--timeout", "10"])
    assert r.exit_code == 0 and "dev@example.com" in r.output and SENTINEL_KEY not in r.output
    assert teamauth.load_key() == SENTINEL_KEY


@pytest.mark.parametrize(("status", "want", "not_want"), [(401, "seen team login", "refused these"), (403, "refused these changes", "seen team login")])
def test_sync_hint_depends_on_status(configured: Fake, status: int, want: str, not_want: str) -> None:
    from seen_core import spool
    from seen_core.db import ledger_session
    from seen_core.db.models import Outbox

    teamauth.save_key("stale")
    with ledger_session() as db:
        db.add(Outbox(kind="batch", payload_json="{}", created_at=spool.now(), attempts=0, dead_at=spool.now(), last_status=status))
        db.commit()
    r = cli.invoke(app, ["sync"])
    assert want in r.output and not_want not in r.output
