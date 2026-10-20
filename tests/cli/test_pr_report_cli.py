"""`seen pr-report`: md and json output, --no-cost, --fail-on exit codes, one-line exit-2 failures."""

import json
import os
from pathlib import Path

import sqlalchemy as sa
from typer.testing import CliRunner

from seen_cli.main import app
from seen_core.db import ledger_session
from seen_core.db.models import Change, Policy, PolicyResult
from seen_core.pii.checked import PII_CHECKED
from tests.conftest import git
from tests.provenance.scenarios import Scene
from tests.provenance.test_scenarios import SCENARIOS

cli = CliRunner()


def run(cwd: Path, *args: str) -> tuple[int, str, str]:
    old = os.getcwd()
    try:
        os.chdir(cwd)
        r = cli.invoke(app, ["pr-report", *args], catch_exceptions=False)
    finally:
        os.chdir(old)
    return r.exit_code, r.stdout, r.stderr


def squash(tmp_path: Path) -> Scene:
    s = Scene(tmp_path, "sq")
    SCENARIOS["squash merge"](s)
    return s


def test_md_and_json(tmp_path: Path) -> None:
    s = squash(tmp_path)
    code, out, _ = run(s.root, "--base", "HEAD~1")
    assert code == 0 and "agent 10" in out and PII_CHECKED in out and "API-equivalent" in out
    code, out, _ = run(s.root, "--base", "HEAD~1", "--format", "json", "--no-cost")
    d = json.loads(out)
    assert code == 0 and d["added"]["agent"] == 10 and d["cost_usd"] is None
    assert "compute_agent" not in out


def test_no_cost_removes_the_line(tmp_path: Path) -> None:
    s = squash(tmp_path)
    assert "API-equivalent" not in run(s.root, "--base", "HEAD~1", "--no-cost")[1]


def test_fail_on_rule_missed(tmp_path: Path) -> None:
    s = squash(tmp_path)
    with ledger_session() as db:
        cid = db.scalars(sa.select(Change.id)).first()
        db.add_all([Policy(id="pol-1", title="llm needs phi check", require_skill="phi"), PolicyResult(change_id=cid, policy_id="pol-1", met=0)])
        db.commit()
    assert run(s.root, "--base", "HEAD~1")[0] == 0
    code, out, err = run(s.root, "--base", "HEAD~1", "--fail-on", "rule-missed")
    assert code == 1 and "llm needs phi check" in out and "rule-missed" in err
    assert run(s.root, "--base", "HEAD~1", "--fail-on", "pii-high")[0] == 0
    code, _, err = run(s.root, "--base", "HEAD~1", "--fail-on", "unapproved-skill")  # the replayed turn runs an unreviewed skill
    assert code == 1 and "unapproved-skill" in err


def _fails(cwd: Path, *args: str, code: int = 2) -> None:
    c, out, err = run(cwd, *args)
    assert c == code, (out, err)
    assert "Traceback" not in out + err and len((out + err).strip().splitlines()) == 1


def test_usage_and_ref_errors(tmp_path: Path) -> None:
    s = squash(tmp_path)
    _fails(s.root, "--base", "HEAD~1", "--fail-on", "bogus")
    _fails(s.root, "--base", "nope")
    _fails(s.root, "--base", "--output=x")
    _fails(s.root, "--base", "HEAD~1", "--format", "xml")


def test_unrecorded_repo(tmp_path: Path) -> None:
    r = tmp_path / "empty"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    _fails(r, "--base", "main")
