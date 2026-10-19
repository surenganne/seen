"""Staleness (plan 9.7), computed at read time from the ledger. Nothing is stored. Stdlib only:
a read-only sqlite3 query, safe to run from the injection hook."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime

from .. import paths
from .files import Memory


def _baseline(m: Memory, con: sqlite3.Connection | None) -> str:
    times = [m.verified_at or ""]
    if m.source_change and con is not None:
        r = con.execute("SELECT coalesce(ended_at, started_at) FROM changes WHERE id = ?", (m.source_change,)).fetchone()
        if r and r[0]:
            times.append(r[0])
    if not any(times):  # never verified, no known source: the file's own age is the baseline
        try:
            times.append(datetime.fromtimestamp(os.path.getmtime(m.path), UTC).isoformat().replace("+00:00", "Z"))
        except OSError:
            pass
    return max(times)


def mark_stale(memories: list[Memory], project_id: str | None) -> list[Memory]:
    db = paths.ledger_db()
    con = None
    if project_id and db.exists():
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        except sqlite3.Error:
            con = None
    try:
        for m in memories:
            m.stale, m.stale_reason = False, None
            if not m.ok or con is None:
                continue
            if not m.source_change and m.scope == "team":
                # nothing writes source_change into the front matter: the latest change that touched the note is its source
                try:
                    r = con.execute("SELECT c.id FROM change_files f JOIN changes c ON c.id = f.change_id WHERE c.project_id = ? "
                                    "AND f.path = ? ORDER BY coalesce(c.ended_at, c.started_at) DESC LIMIT 1",
                                    (project_id, f".seen/memory/{os.path.basename(m.path)}")).fetchone()
                except sqlite3.Error:
                    r = None
                m.source_change = r[0] if r else None
            if not m.file_ref:
                continue
            base = _baseline(m, con)
            try:
                r = con.execute(
                    "SELECT c.seq, coalesce(c.ended_at, c.started_at) AS at, c.id FROM change_files f JOIN changes c ON c.id = f.change_id "
                    "WHERE c.project_id = ? AND f.path = ? AND coalesce(c.ended_at, c.started_at) > ? AND c.id != coalesce(?, '') "
                    "ORDER BY at DESC LIMIT 1", (project_id, m.file_ref, base, m.source_change)).fetchone()
            except sqlite3.Error:
                continue
            if r:
                m.stale = True
                m.stale_reason = f"{m.file_ref} changed in change #{r[0]} on {r[1][:10]} after it was " + \
                    ("verified" if m.verified_at else "written")
    finally:
        if con is not None:
            con.close()
    return memories
