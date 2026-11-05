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


def test_snapshot_is_consistent_self_contained_and_leaves_secrets_behind(tmp_path: Path) -> None:
    src, dest = paths.home(), tmp_path / "snap"
    fill(src)
    snap = snapshot.snapshot(src, dest)
    assert snap.parent == dest and (dest / "current").resolve() == snap.resolve()
    assert sqlite3.connect(snap / "ledger.db").execute("SELECT count(*) FROM t").fetchone() == (3,)
    assert sqlite3.connect(snap / "audit.db").execute("PRAGMA journal_mode").fetchone() == ("delete",)
    assert not list(snap.glob("*-wal")) and not list(snap.glob("*-shm"))
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


@pytest.mark.parametrize("sync_text", [
    '[sync]\nenabled = true\nserver = "https://team.example"\n',
    'sync = { enabled = true, server = "https://team.example" }\n',
    'sync.server = "https://team.example"\nsync.enabled = true\n',
    '[sync]\nserver = "https://team.example"\n[sync.extra]\nk = "v"\n',
])
def test_snapshot_config_drops_the_sync_table_and_keeps_the_rest(tmp_path: Path, sync_text: str) -> None:
    import tomllib

    src, dest = paths.home(), tmp_path / "snap"
    fill(src)
    (src / "config.toml").write_text('top = "kept"\n[pricing]\nlevel = 2\nnames = ["a", "b"]\nok = true\n' + sync_text
                                     if sync_text.startswith("[") else sync_text + 'top = "kept"\n[pricing]\nlevel = 2\nnames = ["a", "b"]\nok = true\n')
    snap = snapshot.snapshot(src, dest)
    text = (snap / "config.toml").read_text()
    cfg = tomllib.loads(text)
    assert "sync" not in cfg and "team.example" not in text and "server" not in text
    assert cfg["top"] == "kept" and cfg["pricing"] == {"level": 2, "names": ["a", "b"], "ok": True}


def test_snapshot_does_not_copy_an_unparsable_config(tmp_path: Path) -> None:
    src, dest = paths.home(), tmp_path / "snap"
    fill(src)
    (src / "config.toml").write_text('[sync\nserver = "https://team.example"\n')
    snap = snapshot.snapshot(src, dest)
    assert not (snap / "config.toml").exists()  # fail closed: the copy never holds what we could not strip


def test_snapshot_config_keeps_datetimes_and_arrays_of_tables(tmp_path: Path) -> None:
    import datetime
    import tomllib

    src, dest = paths.home(), tmp_path / "snap"
    fill(src)
    (src / "config.toml").write_text(
        'since = 2026-01-02T03:04:05Z\nday = 2026-01-02\nat = 03:04:05\nratio = 0.5\n'
        '[sync]\nserver = "https://team.example"\n'
        '[[rules]]\nname = "a"\n[[rules]]\nname = "b"\nwhen = 2026-02-03\n'
        '[pricing]\nlevel = 2\n')
    snap = snapshot.snapshot(src, dest)
    text = (snap / "config.toml").read_text()
    cfg = tomllib.loads(text)  # still valid TOML, so the container does not silently fall back to defaults
    assert "sync" not in cfg and "team.example" not in text
    assert cfg["since"] == datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.UTC) and cfg["day"] == datetime.date(2026, 1, 2)
    assert cfg["at"] == datetime.time(3, 4, 5) and cfg["ratio"] == 0.5 and cfg["pricing"] == {"level": 2}
    assert cfg["rules"] == [{"name": "a"}, {"name": "b", "when": datetime.date(2026, 2, 3)}]
