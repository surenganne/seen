import json
from pathlib import Path

from seen_core.skills import lock

H1, H2 = "a" * 64, "b" * 64


def test_status_approved_changed_unreviewed_blocked(tmp_path: Path) -> None:
    (tmp_path / ".seen").mkdir()
    (tmp_path / ".seen/skills.lock.json").write_text(json.dumps(
        {"approved": {"good": [H1[:7]], "drift": [H1[:7]]}, "blocked": ["bad"]}))
    lk = lock.load(tmp_path)
    assert lock.status(lk, "good", H1) == "approved"
    assert lock.status(lk, "drift", H2) == "changed"
    assert lock.status(lk, "new", H1) == "unreviewed"
    assert lock.status(lk, "bad", H1) == "blocked"


def test_missing_or_broken_lockfile_is_empty(tmp_path: Path) -> None:
    assert lock.status(lock.load(tmp_path), "x", H1) == "unreviewed"
    (tmp_path / ".seen").mkdir()
    (tmp_path / ".seen/skills.lock.json").write_text("{nope")
    assert lock.load(tmp_path).approved == {}


def test_approve_and_block_roundtrip(tmp_path: Path) -> None:
    lock.approve(tmp_path, "s", H1)
    lock.approve(tmp_path, "s", H1)
    assert json.loads((tmp_path / ".seen/skills.lock.json").read_text())["approved"] == {"s": [H1[:7]]}
    lock.block(tmp_path, "s")
    lk = lock.load(tmp_path)
    assert lock.status(lk, "s", H1) == "blocked"
    lock.unblock(tmp_path, "s")
    assert lock.status(lock.load(tmp_path), "s", H1) == "approved"


def test_writers_fail_closed_on_corrupt_lockfile(tmp_path: Path) -> None:
    import pytest

    (tmp_path / ".seen").mkdir()
    bad = '{"approved": {"x": "notalist"}, "blocked": ["evil"]'
    (tmp_path / ".seen/skills.lock.json").write_text(bad)
    with pytest.raises(lock.LockfileError):
        lock.approve(tmp_path, "s", H1)
    with pytest.raises(lock.LockfileError):
        lock.block(tmp_path, "s")
    assert (tmp_path / ".seen/skills.lock.json").read_text() == bad
    (tmp_path / ".seen/skills.lock.json").write_text('{"approved": {"x": "notalist"}, "blocked": []}')
    with pytest.raises(lock.LockfileError):
        lock.approve(tmp_path, "s", H1)
