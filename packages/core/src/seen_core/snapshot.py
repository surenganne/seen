"""Consistent copy of SEEN_HOME for the Docker dashboard (ADR 0011). WAL files cannot be shared across the Docker
Desktop VM (ADR 0008), so the container gets its own self-contained copy and never touches the live ledger."""

from __future__ import annotations

import os
import shutil
import sqlite3
import time
from pathlib import Path

DBS = ("ledger.db", "audit.db")


def _backup(src: Path, dst: Path) -> None:
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=10)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
        d.execute("PRAGMA journal_mode=DELETE")  # one file, no -wal/-shm to go stale when `current` flips
    finally:
        d.close()
        s.close()


def snapshot(src: Path, dest: Path, keep: int = 2, name: str | None = None) -> Path:
    """Copy ledger, audit and config into dest/<utc stamp>/ and point dest/current at it.
    secret.key is never copied: the container only reads."""
    if not (src / DBS[0]).exists():
        raise SystemExit(f"No ledger at {src / DBS[0]}: nothing to snapshot.")
    name = name or time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp, final = dest / f".{name}.tmp", dest / name
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(mode=0o700)
    try:
        # heads first: a head newer than the copied audit.db would read as truncation
        for f in ("audit-heads.log", "config.toml"):
            if (src / f).is_file():
                shutil.copy2(src / f, tmp / f)
        for db in DBS:
            if (src / db).exists():
                _backup(src / db, tmp / db)
        shutil.rmtree(final, ignore_errors=True)
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    link = dest / ".current.tmp"
    link.unlink(missing_ok=True)
    link.symlink_to(name)
    os.replace(link, dest / "current")
    for old in sorted(p for p in dest.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith("."))[:-keep]:
        shutil.rmtree(old, ignore_errors=True)
    return final
