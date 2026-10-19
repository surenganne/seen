from pathlib import Path

import pytest
from typer.testing import CliRunner

from seen_cli.main import app
from seen_core import brand, upgrade
from tests.core.test_upgrade import write_plugins

cli = CliRunner()


def test_version_lists_every_piece(tmp_path: Path) -> None:
    write_plugins(tmp_path, brand.VERSION)
    out = cli.invoke(app, ["version"]).output
    assert brand.VERSION in out and "ledger schema" in out and "plugin" in out and "seen-hook" in out


def test_upgrade_without_yes_only_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade, "run", lambda *_a, **_k: pytest.fail("must not run anything without --yes"))
    r = cli.invoke(app, ["upgrade"])
    assert r.exit_code == 0 and "Would run" in r.output and "uv tool install" in r.output
    assert cli.invoke(app, ["upgrade", "--check"]).exit_code == 0


def test_upgrade_yes_refuses_on_an_unhealthy_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade, "healthy", lambda: (False, "audit chain broken at seq 3"))
    monkeypatch.setattr(upgrade, "run", lambda *_a, **_k: pytest.fail("must not run"))
    r = cli.invoke(app, ["upgrade", "--yes"])
    assert r.exit_code == 1 and "audit chain broken" in r.output


def test_upgrade_yes_runs_the_plan_and_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[list[str]] = []
    monkeypatch.setattr(upgrade, "healthy", lambda: (True, ""))
    monkeypatch.setattr(upgrade, "run", lambda cmds: [(c, 0) for c in ran.extend(cmds) or cmds])
    r = cli.invoke(app, ["upgrade", "--yes", "--source", "/src"])
    assert r.exit_code == 0 and ran[0][:3] == ["uv", "tool", "install"] and "/src" in ran[0]
    assert "restart Claude Code" in r.output


def test_upgrade_yes_exits_nonzero_when_a_step_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade, "healthy", lambda: (True, ""))
    monkeypatch.setattr(upgrade, "run", lambda cmds: [(cmds[0], 2)])
    assert cli.invoke(app, ["upgrade", "--yes"]).exit_code == 1


def test_doctor_flags_skew_and_available_update(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    write_plugins(tmp_path, "0.0.1")
    monkeypatch.setattr(upgrade, "latest_release", lambda **_k: "9.9.9")
    out = cli.invoke(app, ["doctor"]).output
    assert "!!  " in out and "0.0.1" in out and "9.9.9" in out and "seen upgrade" in out
