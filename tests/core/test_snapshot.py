import sqlite3
from pathlib import Path

import pytest

from seen_core import paths, snapshot


def mkdb(path: Path, rows: int) -> None:
    c = sqlite3.connect(path)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE t(x)")
    c.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
    c.commit()  # left open: the WAL stays un-checkpointed, like a live ledger
    globals().setdefault("_keep", []).append(c)


def fill(home: Path, rows: int = 3) -> None:
    home.mkdir(parents=True, exist_ok=True)
    mkdb(home / "ledger.db", rows)
    mkdb(home / "audit.db", rows)
    (home / "audit-heads.log").write_text("head\n")
    (home / "config.toml").write_text("[x]\n")
    (home / "secret.key").write_bytes(b"k" * 32)
    (home / "memory" / "p").mkdir(parents=True)
    (home / "memory" / "p" / "n.md").write_text("note")


def test_snapshot_is_consistent_self_contained_and_leaves_secrets_behind(tmp_path: Path) -> None:
    src, dest = paths.home(), tmp_path / "snap"
    fill(src)
    snap = snapshot.snapshot(src, dest)
    assert snap.parent == dest and (dest / "current").resolve() == snap.resolve()
    assert sqlite3.connect(snap / "ledger.db").execute("SELECT count(*) FROM t").fetchone() == (3,)
    assert sqlite3.connect(snap / "audit.db").execute("PRAGMA journal_mode").fetchone() == ("delete",)
    assert not list(snap.glob("*-wal")) and not list(snap.glob("*-shm"))
    assert (snap / "memory" / "p" / "n.md").read_text() == "note"
    assert (snap / "audit-heads.log").exists() and (snap / "config.toml").exists()
    assert not (snap / "secret.key").exists()


def test_refresh_flips_current_and_keeps_only_two(tmp_path: Path) -> None:
    src, dest = paths.home(), tmp_path / "snap"
    fill(src, 1)
    names = []
    for i in range(4):
        names.append(snapshot.snapshot(src, dest, name=f"2026010{i}T000000").name)
    assert sorted(p.name for p in dest.iterdir() if p.name != "current") == names[-2:]
    assert (dest / "current").resolve().name == names[-1]


def test_missing_ledger_refuses_and_publishes_nothing(tmp_path: Path) -> None:
    src, dest = paths.home(), tmp_path / "snap"
    src.mkdir(parents=True)
    with pytest.raises(SystemExit):
        snapshot.snapshot(src, dest)
    assert not dest.exists() or not list(dest.iterdir())
