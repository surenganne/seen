"""seen import: past Claude Code transcripts -> ledger + audit, through the same redaction and pricing as live capture."""

import json
import os
from pathlib import Path

from seen_core import audit, backfill
from seen_core.db import ledger_session
from seen_core.db.models import Change, ChangeFile, PiiFinding, Session


def _usage(i: int, o: int) -> dict[str, int]:
    return {"input_tokens": i, "output_tokens": o, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 50}


def _write_transcript(repo: Path, sid: str) -> Path:
    d = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / backfill.encode_dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    base = {"sessionId": sid, "cwd": str(repo), "version": "2.1.300"}
    lines = [
        {**base, "type": "user", "uuid": "u1", "promptId": "p1", "timestamp": "2026-10-10T10:00:00.000Z",
         "message": {"role": "user", "content": "Fix a.py, ping jane.doe@fictional-corp.in when done"}},
        {**base, "type": "assistant", "timestamp": "2026-10-10T10:00:05.000Z",
         "message": {"id": "m1", "model": "claude-opus-5-5", "usage": _usage(10, 200), "content": [
             {"type": "tool_use", "id": "t1", "name": "Edit",
              "input": {"file_path": str(repo / "a.py"), "old_string": "one\n", "new_string": "uno\ndos\n"}}]}},
        {**base, "type": "user", "timestamp": "2026-10-10T10:00:06.000Z",
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
        {**base, "type": "assistant", "timestamp": "2026-10-10T10:00:09.000Z",
         "message": {"id": "m2", "model": "claude-opus-5-5", "usage": _usage(5, 40),
                     "content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "pytest -q"}}]}},
        {**base, "type": "assistant", "timestamp": "2026-10-10T10:00:12.000Z",
         "message": {"id": "m3", "model": "claude-opus-5-5", "usage": _usage(1, 30),
                     "content": [{"type": "text", "text": "Fixed the parser in a.py."}]}},
        {**base, "type": "user", "uuid": "u2", "promptId": "p2", "timestamp": "2026-10-10T10:05:00.000Z",
         "message": {"role": "user", "content": "Now write the docs"}},
        {**base, "type": "user", "isMeta": True, "timestamp": "2026-10-10T10:05:00.500Z",
         "message": {"role": "user", "content": "<local-command-stdout>meta</local-command-stdout>"}},
        {**base, "type": "assistant", "timestamp": "2026-10-10T10:05:20.000Z",
         "message": {"id": "m4", "model": "claude-opus-5-5", "usage": _usage(3, 80), "content": [
             {"type": "tool_use", "id": "t3", "name": "Write", "input": {"file_path": str(repo / "README.md"), "content": "a\nb\nc\n"}},
             {"type": "text", "text": "Docs written."}]}},
    ]
    p = d / f"{sid}.jsonl"
    p.write_text("".join(json.dumps(ln) + "\n" for ln in lines))
    return p


def test_import_records_sessions_turns_files_tokens_and_pii(repo: Path) -> None:
    _write_transcript(repo, "sess-old")
    res = backfill.import_project(repo)
    assert res.sessions == 1 and res.changes == 2 and res.skipped == 0
    with ledger_session() as db:
        s = db.get(Session, "sess-old")
        assert s is not None and s.source == "imported" and s.tool_version == "2.1.300"
        assert s.started_at == "2026-10-10T10:00:00.000Z" and s.ended_at == "2026-10-10T10:05:20.000Z"
        ch = sorted(db.query(Change).filter(Change.session_id == "sess-old"), key=lambda c: c.seq or 0)
        assert [c.model for c in ch] == ["claude-opus-5-5"] * 2
        assert (ch[0].tok_in, ch[0].tok_out, ch[0].tok_cache_read, ch[0].tok_cache_write) == (16, 270, 300, 150)
        assert ch[0].cost_usd and ch[0].cost_usd > 0 and ch[0].summary == "Fixed the parser in a.py."
        assert "[EMAIL]" in (ch[0].prompt_text or "") and "fictional-corp" not in (ch[0].prompt_text or "")
        files = {(f.change_id, f.path): (f.added, f.removed) for f in db.query(ChangeFile)}
        assert files[(ch[0].id, "a.py")] == (2, 1) and files[(ch[1].id, "README.md")] == (3, 0)
        pii = [f for f in db.query(PiiFinding) if f.change_id == ch[0].id]
        assert [(f.type, f.source_kind, f.destination) for f in pii] == [("email", "prompt", "model")]
    ev = audit.query(session="sess-old", limit=100)
    types = [e["type"] for e in ev]
    assert types.count("tool.call") == 3 and types.count("turn.start") == 2 and "session.start" in types and "session.end" in types
    assert {e["subject"] for e in ev if e["type"] == "tool.call"} == {"Edit", "Bash", "Write"}
    assert all(e["detail"].get("imported") for e in ev if e["type"] in ("session.start", "turn.end"))
    assert "pytest" not in json.dumps(ev)  # command arguments are never logged
    assert audit.verify().ok


def test_import_is_idempotent_and_skips_live_sessions(repo: Path) -> None:
    _write_transcript(repo, "sess-old")
    _write_transcript(repo, "sess-live")
    with ledger_session() as db:
        db.add(Session(id="sess-live", project_id=None, started_at="2026-10-10T09:00:00.000Z"))
        db.commit()
    first = backfill.import_project(repo)
    assert (first.sessions, first.skipped) == (1, 1)
    again = backfill.import_project(repo)
    assert (again.sessions, again.changes, again.skipped) == (0, 0, 1)  # live sessions are never touched
    with ledger_session() as db:
        assert db.query(Change).filter(Change.session_id == "sess-old").count() == 2


def test_dry_run_writes_nothing(repo: Path) -> None:
    _write_transcript(repo, "sess-old")
    res = backfill.import_project(repo, dry_run=True)
    assert res.sessions == 1 and res.changes == 2
    with ledger_session() as db:
        assert db.get(Session, "sess-old") is None
    assert not audit.query(session="sess-old")


def test_dashboard_marks_imported_data(repo: Path) -> None:
    from fastapi.testclient import TestClient

    from seen_local.app import create_app

    _write_transcript(repo, "sess-old")
    backfill.import_project(repo)
    c = TestClient(create_app(web_dist=None), base_url="http://localhost")
    pid = c.get("/api/projects").json()[0]["id"]
    s = c.get(f"/api/projects/{pid}/sessions").json()["items"]
    assert s[0]["source"] == "imported" and s[0]["status"] == "ended" and s[0]["tool_calls"] == 3
    cid = c.get(f"/api/projects/{pid}/changes").json()["items"][0]["id"]
    assert c.get(f"/api/changes/{cid}").json()["source"] == "imported"


def test_running_session_stays_open_and_reimport_adds_new_turns(repo: Path) -> None:
    from datetime import UTC, datetime

    p = _write_transcript(repo, "sess-now")
    now = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    lines = [json.loads(x) for x in p.read_text().splitlines()]
    lines[-1]["timestamp"] = now  # the transcript is still being written
    p.write_text("".join(json.dumps(x) + "\n" for x in lines))
    backfill.import_project(repo)
    with ledger_session() as db:
        assert db.get(Session, "sess-now").ended_at is None
    assert not [e for e in audit.query(session="sess-now", limit=100) if e["type"] == "session.end"]
    with p.open("a") as f:
        f.write(json.dumps({**lines[0], "uuid": "u3", "promptId": "p3", "timestamp": now,
                            "message": {"role": "user", "content": "and a third thing"}}) + "\n")
    r = backfill.import_project(repo)
    assert (r.sessions, r.changes) == (1, 1)
    with ledger_session() as db:
        assert db.query(Change).filter(Change.session_id == "sess-now").count() == 3
    assert audit.verify().ok
