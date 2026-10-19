from pathlib import Path

from seen_core.db import ledger_session
from seen_core.db.models import Change, ChangeFile
from seen_core.memory import files as mf
from seen_core.memory.stale import mark_stale


def change(cid: str, path: str, at: str, pid: str = "p1", seq: int = 1) -> None:
    with ledger_session() as db:
        db.add(Change(id=cid, project_id=pid, session_id="s", seq=seq, started_at=at, ended_at=at))
        db.add(ChangeFile(change_id=cid, path=path, added=1, removed=0))
        db.commit()


def mem(tmp: Path, verified: str | None, ref: str = "agent/stt.py", src: str | None = None) -> mf.Memory:
    p = mf.new_memory(tmp / ".seen/memory", id="m", type="decision", body="b", file_ref=ref, source_change=src)
    if verified:
        mf.verify(p, verified)
    return mf.parse_file(p, "team")


def test_edit_after_verify_flips_to_stale(tmp_path: Path, seen_home: Path) -> None:
    m = mem(tmp_path, "2026-10-10T00:00:00Z")
    change("c0", "agent/stt.py", "2026-10-09T00:00:00Z")
    assert not mark_stale([m], "p1")[0].stale
    change("c1", "agent/stt.py", "2026-10-12T00:00:00Z", seq=2)
    out = mark_stale([m], "p1")[0]
    assert out.stale and "agent/stt.py" in (out.stale_reason or "") and "#2" in (out.stale_reason or "")


def test_reverify_clears_stale(tmp_path: Path, seen_home: Path) -> None:
    m = mem(tmp_path, "2026-10-10T00:00:00Z")
    change("c1", "agent/stt.py", "2026-10-12T00:00:00Z")
    mf.verify(Path(m.path), "2026-10-13T00:00:00Z")
    assert not mark_stale([mf.parse_file(Path(m.path), "team")], "p1")[0].stale


def test_source_change_time_counts(tmp_path: Path, seen_home: Path) -> None:
    change("src", "agent/stt.py", "2026-10-12T00:00:00Z")
    m = mem(tmp_path, None, src="src")
    assert not mark_stale([m], "p1")[0].stale  # the source change itself does not make it stale
    change("later", "agent/stt.py", "2026-10-14T00:00:00Z", seq=2)
    assert mark_stale([m], "p1")[0].stale


def test_other_project_and_no_ledger(tmp_path: Path, seen_home: Path) -> None:
    m = mem(tmp_path, "2026-10-10T00:00:00Z")
    assert not mark_stale([m], "p1")[0].stale  # no ledger yet
    change("c", "agent/stt.py", "2026-10-12T00:00:00Z", pid="other")
    assert not mark_stale([m], "p1")[0].stale


def test_change_that_wrote_the_note_is_its_source(tmp_path: Path, seen_home: Path) -> None:
    """A note written (by `seen memory add` or the model) in the same turn that edited its file is not stale:
    the change whose files include the note is its source, even with no source_change in the front matter."""
    m = mem(tmp_path, None)
    with ledger_session() as db:
        db.add(Change(id="wrote", project_id="p1", session_id="s", seq=2, started_at="2099-01-01T00:00:00Z", ended_at="2099-01-01T00:05:00Z"))
        db.add(ChangeFile(change_id="wrote", path="agent/stt.py", added=1, removed=0))
        db.add(ChangeFile(change_id="wrote", path=".seen/memory/m.md", added=8, removed=0))
        db.commit()
    out = mark_stale([m], "p1")[0]
    assert not out.stale and out.source_change == "wrote"
    change("later", "agent/stt.py", "2099-01-02T00:00:00Z", seq=3)
    assert mark_stale([m], "p1")[0].stale
