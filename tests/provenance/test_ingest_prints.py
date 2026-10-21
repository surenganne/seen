from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa

from seen_core import ingest, spool
from seen_core.db import ledger_session
from seen_core.db.models import Change, LinePrint, Project
from tests.helpers import Replay

CONTENT = "".join(f"value_{n} = compute_something({n}) + offset\n" for n in range(3)) + "value_0 = compute_something(0) + offset\n"


def drive(repo: Path, tmp_path: Path) -> None:
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    rp.fire("post-tool", "post_tool_use_write", tool_input={"file_path": str(repo / "a.py"), "content": CONTENT})
    rp.model_works()
    rp.stop()


def rows() -> list[LinePrint]:
    with ledger_session() as db:
        return list(db.scalars(sa.select(LinePrint)))


def test_ingest_stores_each_fingerprint_once_per_change(repo: Path, tmp_path: Path) -> None:
    drive(repo, tmp_path)
    with ledger_session() as db:
        cid, pid = db.query(Change.id).one()[0], db.query(Project.id).one()[0]
    got = rows()
    assert len(got) == 3
    assert {(r.change_id, r.project_id, r.path) for r in got} == {(cid, pid, "a.py")}
    assert all(isinstance(r.fp, bytes) and len(r.fp) == 8 for r in got)
    ingest.finish_turn("sess-1")  # re-ingest is idempotent
    assert len(rows()) == 3


def test_malformed_prints_lines_are_skipped(repo: Path, tmp_path: Path) -> None:
    drive(repo, tmp_path)
    for bad in ({"fps": None}, {"fps": "abcd"}, {"fps": ["zz" * 8, "ab"]}, {"path": None, "fps": ["ab" * 8]}, {"fps": [5]}):
        spool.append("sess-1", {"ev": "prints", "prompt_id": "p1", "path": "b.py", **bad})
    ingest.finish_turn("sess-1")
    assert len(rows()) == 3
    with ledger_session() as db:
        ingest._write_prints(db, "c1", None, [{"ev": "prints", "path": "a.py", "fps": ["ab" * 8]}])
        assert len(list(db.scalars(sa.select(LinePrint).where(LinePrint.change_id == "c1")))) == 0
