"""Consistent copy of SEEN_HOME for the Docker dashboard (ADR 0011). WAL files cannot be shared across the Docker
Desktop VM (ADR 0008), so the container gets its own self-contained copy and never touches the live ledger."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
import tomllib
from datetime import date, datetime
from datetime import time as dtime
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


def _val(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime | date | dtime):
        return v.isoformat()  # TOML-native date and time values
    if isinstance(v, list):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{json.dumps(k)} = {_val(x)}" for k, x in v.items()) + "}"
    return json.dumps(v) if isinstance(v, str) else repr(v)


def _toml(d: dict[str, object], prefix: str = "") -> str:
    """Minimal TOML writer for config.toml (scalars, dates, arrays, tables, arrays of tables). JSON string escapes are valid TOML."""
    def is_aot(v: object) -> bool:
        return isinstance(v, list) and bool(v) and all(isinstance(x, dict) for x in v)

    out = "".join(f"{json.dumps(k)} = {_val(v)}\n" for k, v in d.items() if not isinstance(v, dict) and not is_aot(v))
    for k, v in d.items():
        name = f"{prefix}.{json.dumps(k)}" if prefix else json.dumps(k)
        if isinstance(v, dict):
            out += f"\n[{name}]\n" + _toml(v, name)
        elif is_aot(v):
            assert isinstance(v, list)
            for item in v:
                out += f"\n[[{name}]]\n" + _toml(item, name)
    return out


def _config_without_sync(src: Path, dst: Path) -> None:
    """Copy config.toml minus the [sync] table: the container dashboard must not be team-configured (it could mint a
    team key into the host snapshot folder). An unparsable file is not copied at all (fail closed)."""
    try:
        cfg = tomllib.loads(src.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return
    cfg.pop("sync", None)
    dst.write_text(_toml(cfg))


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
        if (src / "audit-heads.log").is_file():
            shutil.copy2(src / "audit-heads.log", tmp / "audit-heads.log")
        if (src / "config.toml").is_file():
            _config_without_sync(src / "config.toml", tmp / "config.toml")
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
