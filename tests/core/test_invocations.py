from pathlib import Path

import pytest
import sqlalchemy as sa
from seen_core.db import ledger_engine
from seen_core.invocations import reconcile
from seen_core.transcript import parse_turn

from tests.conftest import FIXTURES
from tests.core.test_skills import mkskill
from tests.helpers import Replay

TR = FIXTURES / "transcripts"


def inv(*names: str) -> dict[str, dict]:
    return {n: {"id": n, "hash": "h" * 64, "kind": "project"} for n in names}


def test_recall_all_eleven_from_transcript() -> None:
    t = parse_turn(TR / "recall.jsonl", 0)
    got = reconcile([], t, "do the ticks", inv("tick-skill", "greet-skill"))
    assert [g.skill_id for g in got] == ["tick-skill"] * 10 + ["greet-skill"]
    assert all(g.trigger == "model" and g.hash == "h" * 64 for g in got)


def test_spool_and_transcript_deduped_by_tool_use_id() -> None:
    t = parse_turn(TR / "recall.jsonl", 0)
    spool = [{"ev": "skill_start", "skill": c.name, "tool_use_id": c.tool_use_id, "trigger": "model"} for c in t.skill_calls]
    spool.append({"ev": "skill_start", "skill": "late-skill", "tool_use_id": "toolu_only_in_spool", "trigger": "model"})
    got = reconcile(spool, t, "", inv("tick-skill", "greet-skill"))
    assert len(got) == 12 and got[-1].skill_id == "late-skill" and got[-1].kind == "sideload"


def test_slash_skill_is_user_trigger_once() -> None:
    t = parse_turn(TR / "slash.jsonl", 0)
    got = reconcile([], t, "/greet-skill", inv("greet-skill"))
    assert [(g.skill_id, g.trigger) for g in got] == [("greet-skill", "user")]


def test_builtin_slash_commands_ignored() -> None:
    assert reconcile([], parse_turn(TR / "run1.jsonl", 0), "/clear", inv("greet-skill")) [0].trigger == "model"


def test_subagent_trigger() -> None:
    t = parse_turn(TR / "subagent.jsonl", 0)
    got = reconcile([], t, "", inv("greet-skill"))
    assert [(g.skill_id, g.trigger) for g in got] == [("greet-skill", "subagent")]


def test_invocations_written_by_ingest(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEEN_INVENTORY_SYNC", "1")
    mkskill(repo / ".claude/skills", "greet-skill")
    r = Replay(repo, tmp_path)
    r.start()
    r.prompt()
    r.fire("pre-skill", "pre_tool_use_skill")
    r.model_works()
    r.stop()
    with ledger_engine().connect() as c:
        rows = c.execute(sa.text("select ordinal, skill_id, trigger, hash from skill_invocations")).all()
    assert [(o, s, t) for o, s, t, _ in rows] == [(1, "greet-skill", "model")]
    assert rows[0][3] and len(rows[0][3]) == 64
