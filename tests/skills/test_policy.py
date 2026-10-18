import json
from pathlib import Path

import pytest
import sqlalchemy as sa

from seen_core import audit, policy, spool
from seen_core.db import ledger_engine
from tests.core.test_skills import mkskill
from tests.helpers import Replay


def rows(sql: str) -> list[tuple]:
    with ledger_engine().connect() as c:
        return [tuple(r) for r in c.execute(sa.text(sql))]


def policies(repo: Path, mode: str = "report") -> None:
    (repo / ".seen").mkdir(exist_ok=True)
    (repo / ".seen/policies.yaml").write_text(
        f'- id: pol-llm\n  title: PHI redaction check on LLM code\n  paths: ["llm/**"]\n  require_skill: greet-skill\n  mode: {mode}\n')


def test_load_and_match(tmp_path: Path) -> None:
    policies(tmp_path)
    ps = policy.load(tmp_path)
    assert ps[0].id == "pol-llm" and ps[0].mode == "report"
    assert policy.evaluate(ps, ["llm/a.py", "x.py"], set()) == [("pol-llm", False)]
    assert policy.evaluate(ps, ["llm/sub/b.py"], {"greet-skill"}) == [("pol-llm", True)]
    assert policy.evaluate(ps, ["src/x.py"], set()) == []


def test_bad_policies_file_is_reported_not_fatal(tmp_path: Path) -> None:
    (tmp_path / ".seen").mkdir()
    (tmp_path / ".seen/policies.yaml").write_text("- id: x\n  paths: notalist\n- {{{")
    assert policy.load(tmp_path) == []


def turn(repo: Path, tmp_path: Path, sid: str = "sess-1", skill: bool = False, active: bool = False) -> object:
    r = Replay(repo, tmp_path, sid=sid)
    r.start()
    r.prompt()
    (repo / "llm").mkdir(exist_ok=True)
    (repo / "llm/summarise.py").write_text("x = 1\n")
    if skill:
        r.fire("pre-skill", "pre_tool_use_skill")
    return r


def test_report_mode_records_missed_never_blocks(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEEN_INVENTORY_SYNC", "1")
    policies(repo)
    r = turn(repo, tmp_path)
    res = r.stop()
    assert res.code == 0 and "block" not in res.stdout
    assert [(p.split(":")[-1], m) for p, m in rows("select policy_id, met from policy_results")] == [("pol-llm", 0)]
    assert audit.query(type_="policy.result")[0]["outcome"] == "failed"


def test_enforce_mode_blocks_once_then_lets_go(repo: Path, tmp_path: Path) -> None:
    policies(repo, "enforce")
    r = turn(repo, tmp_path)
    first = r.stop()
    out = json.loads(first.stdout)
    assert out["decision"] == "block" and "greet-skill" in out["reason"] and "llm/summarise.py" in out["reason"]
    second = r.stop(stop_hook_active=True)  # Claude continued but still did not run it: never loop
    assert "block" not in second.stdout


def test_met_when_skill_ran(repo: Path, tmp_path: Path) -> None:
    policies(repo, "enforce")
    r = turn(repo, tmp_path, skill=True)
    assert "block" not in r.stop().stdout
    assert rows("select met from policy_results") == [(1,)]


def test_invocation_records_status_at_that_moment(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_core.skills import lock

    monkeypatch.setenv("SEEN_INVENTORY_SYNC", "1")
    d = mkskill(repo / ".claude/skills", "greet-skill", extra={"run.sh": "echo 1\n"})
    from seen_core.skills.hashing import hash_folder

    lock.approve(repo, "greet-skill", hash_folder(d))
    r = turn(repo, tmp_path, skill=True)
    r.model_works()
    r.stop()
    (d / "run.sh").write_text("echo 2\n")  # edited after approval
    import os

    os.utime(d / "run.sh", ns=(1, 10**18))
    r2 = turn(repo, tmp_path, sid="sess-2", skill=True)
    r2.model_works()
    r2.stop()
    assert sorted(s for (s,) in rows("select status from skill_invocations")) == ["approved", "changed"]
    assert {e["detail"]["status"] for e in audit.query(type_="skill.invoked")} == {"approved", "changed"}


def test_blocked_skill_refused_at_pre_skill(repo: Path, tmp_path: Path) -> None:
    from seen_core.skills import lock

    lock.block(repo, "greet-skill")
    r = Replay(repo, tmp_path)
    r.start()
    r.prompt()
    res = r.fire("pre-skill", "pre_tool_use_skill")
    assert res.code == 2 and "blocked" in res.stderr
    gate = [x for x in spool.read("sess-1") if x["ev"] == "gate"]
    assert gate[-1]["decision"] == "block" and gate[-1]["hook"] == "pre-skill"
