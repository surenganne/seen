"""Append-only, hash-chained audit trail (plan 11A). Own SQLite file, stdlib only.

hash = sha256(prev_hash + canonical_json(all fields except hash)); first prev = 64 zeros.
Triggers abort UPDATE and DELETE: that stops bugs and accidents, not a determined local
user. The chain is tamper-evident only once heads are anchored off the machine (Phase 5).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from . import paths, spool

ZERO = "0" * 64
FIELDS = ["seq", "event_id", "occurred_at", "recorded_at", "actor_kind", "actor_id", "project_id", "session_id",
          "change_id", "type", "subject", "outcome", "detail_json", "prev_hash"]
# detail_json never holds content: these keys are refused outright, and long strings too
FORBIDDEN_KEYS = {"prompt", "prompt_text", "command", "args", "content", "diff", "text", "value", "body", "message", "output"}
MAX_STR = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE, occurred_at TEXT, recorded_at TEXT,
  actor_kind TEXT, actor_id TEXT, project_id TEXT, session_id TEXT, change_id TEXT,
  type TEXT, subject TEXT, outcome TEXT, detail_json TEXT, prev_hash TEXT, hash TEXT);
CREATE INDEX IF NOT EXISTS audit_project ON audit_events(project_id, seq);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
  BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
  WHEN (SELECT count(*) FROM audit_prune_token) = 0
  BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
"""


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_hash(row: dict[str, Any]) -> str:
    body = {k: row.get(k) for k in FIELDS}
    return hashlib.sha256(str(row.get("prev_hash") or "").encode() + canonical(body)).hexdigest()


def connect() -> sqlite3.Connection:
    db = paths.audit_db()
    paths.ensure_dir(db.parent)
    import os

    if not db.exists():
        os.close(os.open(db, os.O_CREAT | os.O_WRONLY, 0o600))
    c = sqlite3.connect(db, isolation_level=None, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE IF NOT EXISTS audit_prune_token(x INTEGER)")
    c.executescript(SCHEMA)
    return c


def check_detail(detail: Any, path: str = "detail") -> None:
    if isinstance(detail, dict):
        for k, v in detail.items():
            if str(k).lower() in FORBIDDEN_KEYS:
                raise ValueError(f"audit {path}.{k}: content keys are not allowed")
            check_detail(v, f"{path}.{k}")
    elif isinstance(detail, list | tuple):
        for i, v in enumerate(detail):
            check_detail(v, f"{path}[{i}]")
    elif isinstance(detail, str):
        if len(detail) > MAX_STR:
            raise ValueError(f"audit {path}: string longer than {MAX_STR} chars (content is not allowed)")
    elif detail is not None and not isinstance(detail, int | float | bool):
        raise ValueError(f"audit {path}: unsupported type {type(detail).__name__}")


def append(events: Iterable[dict[str, Any]], conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    """Append events in one BEGIN IMMEDIATE transaction. Returns the stored rows."""
    evs = list(events)
    for e in evs:
        if e.get("type") == "audit.checkpoint" and conn is None:
            raise ValueError("audit.checkpoint is written only by the retention prune")  # it vouches for missing rows
        check_detail(e.get("detail") or {})
        for k in ("subject", "actor_id", "project_id", "session_id", "change_id", "type", "outcome", "event_id"):
            v = e.get(k)
            if v is not None and (not isinstance(v, str) or len(v) > MAX_STR):
                raise ValueError(f"audit {k}: must be a short string")
    c = conn or connect()
    own = conn is None
    out = []
    try:
        if own:
            c.execute("BEGIN IMMEDIATE")
        last = c.execute("SELECT seq, hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        seq, prev = (last[0], last[1]) if last else (0, ZERO)
        now = spool.now()
        for e in evs:
            if e.get("event_id") and c.execute("SELECT 1 FROM audit_events WHERE event_id=?", (e["event_id"],)).fetchone():
                continue  # deterministic ids make a repeated ingest a no-op; checked under the write lock, so a race cannot fail the batch
            seq += 1
            row = {"seq": seq, "event_id": e.get("event_id") or uuid.uuid4().hex, "occurred_at": e.get("occurred_at") or now,
                   "recorded_at": now, "actor_kind": e.get("actor_kind", "system"), "actor_id": e.get("actor_id"),
                   "project_id": e.get("project_id"), "session_id": e.get("session_id"), "change_id": e.get("change_id"),
                   "type": e["type"], "subject": e.get("subject"), "outcome": e.get("outcome", "ok"),
                   "detail_json": canonical(e.get("detail") or {}).decode(), "prev_hash": prev}
            row["hash"] = compute_hash(row)
            c.execute(f"INSERT INTO audit_events({','.join([*FIELDS, 'hash'])}) VALUES ({','.join('?' * (len(FIELDS) + 1))})",
                      [row[k] for k in [*FIELDS, "hash"]])
            prev = row["hash"]
            out.append(row)
        if own:
            c.execute("COMMIT")
    except BaseException:
        if own:
            c.execute("ROLLBACK")
        raise
    finally:
        if own:
            c.close()
    return out


@dataclass
class VerifyResult:
    ok: bool
    count: int
    head: str
    head_seq: int
    break_seq: int | None = None
    expected: str | None = None
    found: str | None = None
    reason: str | None = None
    verified_at: str = ""


def _heads() -> dict[int, str]:
    out: dict[int, str] = {}
    try:
        for ln in paths.audit_heads().read_text().splitlines():
            parts = ln.split()
            if len(parts) >= 3:
                out[int(parts[1])] = parts[2]
    except (OSError, ValueError):
        pass
    return out


def _checkpoints(c: sqlite3.Connection) -> list[tuple[int, str]]:
    """(pruned_to_seq, last_pruned_hash) of every well-formed checkpoint; a malformed one vouches for nothing."""
    out = []
    for (d,) in c.execute("SELECT detail_json FROM audit_events WHERE type='audit.checkpoint'"):
        try:
            x = json.loads(d)
            if isinstance(x["pruned_to_seq"], int) and isinstance(x["last_pruned_hash"], str):
                out.append((x["pruned_to_seq"], x["last_pruned_hash"]))
        except (ValueError, KeyError, TypeError):
            continue
    return out


def verify() -> VerifyResult:
    c = connect()
    try:
        cur = c.execute(f"SELECT {','.join([*FIELDS, 'hash'])} FROM audit_events ORDER BY seq")
        prev, count, last_seq, head = None, 0, 0, ZERO
        checkpoints: set[str] = {ZERO}
        for vals in cur:
            row = dict(zip([*FIELDS, "hash"], vals, strict=True))
            if prev is None:  # first remaining row: genesis, or the hash a prune checkpoint recorded
                checkpoints |= {h for _s, h in _checkpoints(c)}
                if row["prev_hash"] not in checkpoints:
                    return VerifyResult(False, count, head, last_seq, row["seq"], ZERO, row["prev_hash"], "bad genesis", spool.now())
            elif row["prev_hash"] != prev or row["seq"] != last_seq + 1:
                return VerifyResult(False, count, head, last_seq, row["seq"], prev, row["prev_hash"], "chain link broken", spool.now())
            expect = compute_hash(row)
            if expect != row["hash"]:
                return VerifyResult(False, count, head, last_seq, row["seq"], expect, row["hash"], "row edited", spool.now())
            prev, last_seq, head = row["hash"], row["seq"], row["hash"]
            count += 1
        # a checkpoint can only vouch for rows that are really gone: the range below the first remaining row. A claim
        # beyond that (a forged checkpoint hiding a truncated tail) is clamped to what is actually missing.
        first = c.execute("SELECT min(seq) FROM audit_events").fetchone()[0] or 1
        pruned_to = min(max((t for t, _h in _checkpoints(c)), default=0), first - 1)
        for seq, h in sorted(_heads().items()):  # recorded heads catch tail truncation
            if seq <= pruned_to:
                continue  # retention removed it on purpose; the checkpoint vouches for that range
            got = c.execute("SELECT hash FROM audit_events WHERE seq=?", (seq,)).fetchone()
            if got is None or got[0] != h:
                return VerifyResult(False, count, head, last_seq, last_seq + 1 if got is None else seq, h,
                                    got[0] if got else None, "recorded head missing (truncated?)", spool.now())
        return VerifyResult(True, count, head, last_seq, verified_at=spool.now())
    finally:
        c.close()


def record_head() -> str:
    c = connect()
    try:
        last = c.execute("SELECT seq, hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    finally:
        c.close()
    if not last:
        return ZERO
    f = paths.audit_heads()
    paths.ensure_dir(f.parent)
    with open(f, "a") as fh:
        fh.write(f"{spool.now()} {last[0]} {last[1]}\n")
    return str(last[1])


def prune_before_seq(seq: int) -> None:
    """Retention prune. Deletes seq < `seq` and writes audit.checkpoint so the rest verifies."""
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        last = c.execute("SELECT seq, hash FROM audit_events WHERE seq < ? ORDER BY seq DESC LIMIT 1", (seq,)).fetchone()
        if last is None:
            c.execute("ROLLBACK")
            return
        first = c.execute("SELECT min(seq) FROM audit_events").fetchone()[0]
        c.execute("INSERT INTO audit_prune_token VALUES (1)")
        c.execute("DELETE FROM audit_events WHERE seq < ?", (seq,))
        c.execute("DELETE FROM audit_prune_token")
        append([{"type": "audit.checkpoint", "actor_kind": "system",
                 "detail": {"pruned_from_seq": first, "pruned_to_seq": last[0], "last_pruned_hash": last[1]}}], conn=c)
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def prune_older_than(days: int) -> None:
    from datetime import UTC, datetime, timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    c = connect()
    try:
        r = c.execute("SELECT min(seq) FROM audit_events WHERE recorded_at >= ?", (cutoff,)).fetchone()
    finally:
        c.close()
    if r and r[0]:
        prune_before_seq(r[0])


def query(project_id: str | None = None, type_: str | None = None, actor: str | None = None, session: str | None = None,
          date_from: str | None = None, date_to: str | None = None, q: str | None = None,
          limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    where, args = [], []
    for col, val in (("project_id", project_id), ("actor_id", actor), ("session_id", session)):
        if val:
            where.append(f"{col} = ?")
            args.append(val)
    if type_:
        where.append("type LIKE ?")
        args.append(type_.replace("*", "%") if "*" in type_ else type_)
    if date_from:
        where.append("occurred_at >= ?")
        args.append(date_from)
    if date_to:
        where.append("occurred_at <= ?")
        args.append(date_to + ("T23:59:59.999Z" if len(date_to) == 10 else ""))
    if q:
        where.append("(subject LIKE ? OR type LIKE ? OR detail_json LIKE ?)")
        args += [f"%{q}%"] * 3
    sql = f"SELECT {','.join([*FIELDS, 'hash'])} FROM audit_events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY seq DESC LIMIT ? OFFSET ?"
    c = connect()
    try:
        rows = [dict(zip([*FIELDS, "hash"], v, strict=True)) for v in c.execute(sql, [*args, limit, offset])]
    finally:
        c.close()
    for r in rows:
        r["detail"] = json.loads(r.pop("detail_json") or "{}")
    return rows
