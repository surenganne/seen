"""Sessions carry Claude Code's entrypoint (cli, sdk-cli, sdk-py...) so plugin-started background sessions are
told apart from the person's own (spike: spikes/entrypoint_env.md)."""

import json
from pathlib import Path

import pytest

from seen_core import backfill, spool
from seen_core.db import ledger_session
from seen_core.db.models import Session
from tests.core.test_backfill import _write_transcript
from tests.helpers import Replay


def test_live_session_records_entrypoint(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-py")
    r = Replay(repo, tmp_path, sid="bg-1")
    r.start()
    assert spool.read("bg-1")[0]["entrypoint"] == "sdk-py"
    r.prompt()
    r.model_works()
    r.stop()
    with ledger_session() as db:
        s = db.get(Session, "bg-1")
        assert s is not None and s.entrypoint == "sdk-py"


def test_import_records_entrypoint_and_fills_known_sessions(repo: Path) -> None:
    p = _write_transcript(repo, "sess-bg")
    p.write_text("".join(json.dumps({**json.loads(ln), "entrypoint": "sdk-cli"}) + "\n" for ln in p.read_text().splitlines()))
    backfill.import_project(repo)
    with ledger_session() as db:
        assert db.get(Session, "sess-bg").entrypoint == "sdk-cli"  # type: ignore[union-attr]
        db.add(Session(id="sess-live", project_id=db.get(Session, "sess-bg").project_id))  # type: ignore[union-attr]
        db.commit()
    q = _write_transcript(repo, "sess-live")
    q.write_text("".join(json.dumps({**json.loads(ln), "entrypoint": "cli"}) + "\n" for ln in q.read_text().splitlines()))
    res = backfill.import_project(repo)
    assert res.skipped == 1  # a live-recorded session is never re-imported, but its missing entrypoint is filled
    with ledger_session() as db:
        assert db.get(Session, "sess-live").entrypoint == "cli"  # type: ignore[union-attr]
