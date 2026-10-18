import json
from pathlib import Path

import pytest
from seen_core import audit, ingest, paths, spool

from tests.core.test_skills import mkskill
from tests.helpers import Replay


def types() -> list[str]:
    return [e["type"] for e in reversed(audit.query(limit=10_000))]


def test_replayed_session_event_sequence(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEEN_INVENTORY_SYNC", "1")
    mkskill(repo / ".claude/skills", "greet-skill")
    r = Replay(repo, tmp_path)
    r.start()
    r.prompt("secret prompt text SENTINEL-77")
    r.fire("pre-skill", "pre_tool_use_skill")
    (repo / "a.py").write_text("one\ntwo\nthree\n")
    r.fire("post-tool", "post_tool_use_edit", tool_input={"file_path": str(repo / "a.py"), "old_string": "x", "new_string": "SENTINEL-77"})
    r.fire("post-tool", "post_tool_use_bash", tool_input={"command": "curl -H 'Authorization: SENTINEL-77' x"})
    r.model_works()
    r.stop()
    r.fire("session-end", "session_end")
    assert types() == ["session.start", "turn.start", "tool.call", "tool.call", "skill.invoked", "file.changed",
                       "turn.end", "session.end"]
    assert audit.verify().ok
    blob = json.dumps(audit.query(limit=10_000))
    assert "SENTINEL-77" not in blob  # no prompt text, diff or command args, ever
    ts = next(e for e in audit.query(type_="turn.start"))
    assert ts["detail"]["prompt_len"] == len("secret prompt text SENTINEL-77") and len(ts["detail"]["prompt_sha256"]) == 64
    bash = [e for e in audit.query(type_="tool.call") if e["detail"]["tool"] == "Bash"][0]
    assert bash["detail"]["cmd0"] == "curl"
    te = next(e for e in audit.query(type_="turn.end"))
    assert te["detail"]["tok_out"] == 733 and te["change_id"]
    assert paths.audit_heads().read_text().strip()


def test_ingest_twice_writes_events_once(repo: Path, tmp_path: Path) -> None:
    r = Replay(repo, tmp_path)
    r.start()
    r.prompt()
    r.model_works()
    r.stop()
    n = len(types())
    ingest.audit_spool("sess-1")
    ingest.audit_spool("sess-1")
    assert len(types()) == n


def test_killed_session_marked_incomplete(repo: Path, tmp_path: Path) -> None:
    r = Replay(repo, tmp_path, sid="killed")
    r.start()
    r.prompt()
    ingest.sweep_incomplete(max_age_s=0)
    inc = audit.query(type_="session.incomplete")
    assert len(inc) == 1 and inc[0]["session_id"] == "killed" and "last_seq" in inc[0]["detail"]
    ingest.sweep_incomplete(max_age_s=0)
    assert len(audit.query(type_="session.incomplete")) == 1


def test_broken_hook_produces_capture_gap(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_core import hook

    r = Replay(repo, tmp_path)
    r.start()
    r.prompt()
    monkeypatch.setattr(hook, "_on_post_tool", lambda p: 1 / 0)
    r.fire("post-tool", "post_tool_use_edit")
    r.model_works()
    r.stop()
    gap = audit.query(type_="capture.gap")
    assert gap and gap[0]["detail"] == {"error": "ZeroDivisionError", "hook": "post-tool"}


def test_lockfile_change_between_sessions_detected(repo: Path, tmp_path: Path) -> None:
    (repo / ".seen").mkdir()
    (repo / ".seen/skills.lock.json").write_text('{"approved": {}, "blocked": []}')
    r = Replay(repo, tmp_path)
    r.start()
    r.prompt()
    r.model_works()
    r.stop()
    (repo / ".seen/skills.lock.json").write_text('{"approved": {"x": ["abc1234"]}, "blocked": []}')
    r2 = Replay(repo, tmp_path, sid="sess-2")
    r2.start()
    r2.prompt()
    r2.model_works()
    r2.stop()
    ch = audit.query(type_="lockfile.changed")
    assert len(ch) == 1 and ch[0]["detail"]["old"] != ch[0]["detail"]["new"]
    assert spool.read("sess-2")[0]["lock_hash"] == ch[0]["detail"]["new"]
