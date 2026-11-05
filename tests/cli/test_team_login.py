from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seen_cli.main import app
from seen_core import paths, teamauth
from tests.core.teamfakes import SENTINEL_KEY, Fake, fakes

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


def test_logout_clears_key(configured: Fake) -> None:
    teamauth.save_key("k")
    assert cli.invoke(app, ["team", "logout"]).exit_code == 0
    assert teamauth.load_key() is None
    assert cli.invoke(app, ["team", "logout"]).exit_code == 0


def test_login_command_output_has_no_secrets(configured: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    real = teamauth.login
    monkeypatch.setattr(teamauth, "login", lambda timeout_s=300: real(open_browser=configured.browser(), timeout_s=timeout_s))
    r = cli.invoke(app, ["team", "login", "--timeout", "10"])
    assert r.exit_code == 0 and "dev@example.com" in r.output and SENTINEL_KEY not in r.output
    assert teamauth.load_key() == SENTINEL_KEY


def test_sync_hints_login_on_rejection(configured: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_core import spool
    from seen_core.db import ledger_session
    from seen_core.db.models import Outbox

    teamauth.save_key("stale")
    with ledger_session() as db:
        db.add(Outbox(kind="batch", payload_json="{}", created_at=spool.now(), attempts=0, dead_at=spool.now(), last_status=401))
        db.commit()
    r = cli.invoke(app, ["sync"])
    assert "seen team login" in r.output
