import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa

from seen_core import audit, paths, purge
from seen_core.db import ledger_engine, ledger_session
from seen_core.db.models import Change, Project, Session
from tests.helpers import Replay

WORD = "sentinelerasureword"


def record(repo: Path, tmp_path: Path, sid: str = "sess-1") -> None:
    r = Replay(repo, tmp_path, sid=sid)
    r.start()
    r.prompt(f"add mul to calc {WORD}")
    r.model_works()
    r.stop()


def raw() -> bytes:
    """Main file plus WAL: fresh rows sit in the WAL until a checkpoint."""
    db = paths.ledger_db()
    wal = db.with_name(db.name + "-wal")
    return db.read_bytes() + (wal.read_bytes() if wal.exists() else b"")


def counts() -> dict[str, int]:
    with ledger_engine().connect() as c:
        return {t: c.execute(sa.text(f"select count(*) from {t}")).scalar() or 0
                for t in ("changes", "change_files", "sessions", "projects")}


def test_requires_a_scope() -> None:
    with pytest.raises(ValueError):
        purge.purge(actor="u_test")


def test_dry_run_deletes_nothing(repo: Path, tmp_path: Path) -> None:
    record(repo, tmp_path)
    before = counts()
    res = purge.purge(everything=True, actor="u_test", dry_run=True)
    assert res["changes"] == before["changes"] > 0 and counts() == before


def test_project_purge_erases_rows_and_bytes_and_leaves_an_audit_event(repo: Path, tmp_path: Path) -> None:
    record(repo, tmp_path)
    with ledger_session() as db:
        pid = db.query(Project).one().id
    assert WORD.encode() in raw()
    res = purge.purge(project=pid, actor="u_test")
    assert res["changes"] >= 1 and set(counts().values()) == {0}
    assert WORD.encode() not in raw()
    ev = [e for e in audit.query(limit=10000) if e["type"] == "ledger.purge"]
    assert len(ev) == 1 and ev[0]["actor_id"] == "u_test" and WORD not in str(ev[0])
    assert audit.verify().ok


def test_before_keeps_newer_and_other_projects(repo: Path, tmp_path: Path) -> None:
    record(repo, tmp_path, "old")
    record(repo, tmp_path, "new")
    with ledger_session() as db:
        old = db.query(Change).filter(Change.session_id == "old").one()
        old.started_at = "2020-01-01T00:00:00.000Z"
        db.query(Session).filter(Session.id == "old").one().started_at = "2020-01-01T00:00:00.000Z"
        db.commit()
    purge.purge(before="2021-01-01", actor="u_test")
    with ledger_session() as db:
        assert [c.session_id for c in db.query(Change)] == ["new"]
        assert [s.id for s in db.query(Session)] == ["new"] and db.query(Project).count() == 1
    sqlite3.connect(paths.ledger_db()).execute("select 1")
