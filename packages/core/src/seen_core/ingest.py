"""Spool + transcript + git -> ledger rows. Runs at Stop and SessionEnd (not the hot path)."""

from __future__ import annotations

import hashlib
import os
import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select

from . import gitdelta, gitutil, paths, pricing, spool
from .db import ledger_session
from .db.models import Change, ChangeFile, Project, Session, Skill, SkillInvocation, SkillVersion
from .invocations import Invocation, reconcile
from .hook import EDIT_TOOLS
from .transcript import Turn, parse_turn


def change_id(session_id: str, prompt_id: str | None, t: str) -> str:
    return "ch_" + hashlib.sha1(f"{session_id}|{prompt_id or t}".encode()).hexdigest()[:16]


def summarise(text: str) -> str:
    first = re.split(r"(?<=[.!?])\s|\n", text.strip(), maxsplit=1)[0].strip()
    return first[:120]


def _secs(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    return int((datetime.fromisoformat(b.replace("Z", "+00:00")) - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds())


def _current_turn(lines: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    starts = [i for i, ln in enumerate(lines) if ln.get("ev") == "turn_start"]
    return lines[starts[-1]:] if starts else None


def _main_model(t: Turn) -> str | None:
    if not t.usage:
        return None
    return max(t.usage, key=lambda m: t.usage[m]["tok_out"])


def _sum(t: Turn, k: str) -> int:
    return sum(u[k] for u in t.usage.values())


def finish_turn(session_id: str) -> dict[str, Any]:
    lines = spool.read(session_id)
    turn_lines = _current_turn(lines)
    if not turn_lines:
        return {}
    ts = turn_lines[0]
    end = next((ln for ln in reversed(turn_lines) if ln.get("ev") == "turn_end"), None)
    start = next((ln for ln in lines if ln.get("ev") == "session_start"), {})
    cid = change_id(session_id, ts.get("prompt_id"), ts["t"])

    snap: dict[str, Any] = {}
    sf = paths.snap_file(session_id)
    if sf.exists():
        snap = json.loads(sf.read_text())
    before = snap.get("before") if snap.get("prompt_id") == ts.get("prompt_id") else None
    cwd = ts.get("cwd") or "."
    files: dict[str, tuple[int, int]] = {}
    head_after = None
    if before is not None:
        after = gitdelta.snapshot(cwd, base=before["head"])
        head_after = after["head"]
        hints = [ln["path"] for ln in turn_lines if ln.get("ev") == "tool" and ln.get("tool") in EDIT_TOOLS and ln.get("path")]
        top = (gitutil.run(cwd, "rev-parse", "--show-toplevel") or cwd).strip()
        files = gitdelta.delta(before, after, hints=[_expand(h) for h in hints], root=top)

    tp = start.get("transcript_path") or ts.get("transcript_path")
    t = parse_turn(tp, int(ts.get("transcript_offset") or 0)) if tp else Turn()
    cost, price_version = pricing.cost(t.usage)
    last = (end or {}).get("last_message") or t.last_text

    with ledger_session() as db:
        pid = start.get("project_id")
        if pid and db.get(Project, pid) is None:
            db.add(Project(id=pid, name=start.get("project_name"), remote=start.get("remote"),
                           root_path=start.get("root"), created_at=start.get("t")))
        sess = db.get(Session, session_id)
        if sess is None:
            sess = Session(id=session_id, project_id=pid, started_at=start.get("t") or ts["t"], tool="claude-code",
                           user_id=_user_id())
            db.add(sess)
        if t.version and not sess.tool_version:
            sess.tool_version = t.version
        row = db.get(Change, cid)
        if row is None:
            seq = (db.scalar(select(func.count()).select_from(Change).where(Change.session_id == session_id)) or 0) + 1
            row = Change(id=cid, session_id=session_id, project_id=pid, seq=seq)
            db.add(row)
        row.started_at = ts["t"]
        row.ended_at = (end or {}).get("t") or spool.now()
        row.duration_s = _secs(row.started_at, row.ended_at)
        row.prompt_text = None  # stored only through redact.py (P4B-2); never raw by default
        row.summary = summarise(last) if last else None
        row.model = _main_model(t)
        row.tok_in, row.tok_out = _sum(t, "tok_in"), _sum(t, "tok_out")
        row.tok_cache_read, row.tok_cache_write = _sum(t, "tok_cache_read"), _sum(t, "tok_cache_write")
        row.cost_usd, row.price_version = cost, price_version
        row.git_head_before = before["head"] if before else None
        row.git_head_after = head_after
        row.git_status = ("committed" if head_after != row.git_head_before else "uncommitted") if files else None
        row.mem_state = row.mem_state or "none"
        _sync_inventory(db, pid)
        db.execute(delete(ChangeFile).where(ChangeFile.change_id == cid))
        for path, (a, r) in sorted(files.items()):
            db.add(ChangeFile(change_id=cid, path=path, added=a, removed=r))
        invs = reconcile(turn_lines, t, ts.get("prompt") or "", {s["id"]: s for s in inventory(pid)})
        _write_invocations(db, cid, invs)
        db.commit()
    return {"change_id": cid, "files": sorted(files), "turn": t, "turn_lines": turn_lines, "session_start": start,
            "invocations": invs}


def finish_session(session_id: str) -> None:
    with ledger_session() as db:
        sess = db.get(Session, session_id)
        if sess is None:
            return
        sess.ended_at = spool.now()
        for ch in db.scalars(select(Change).where(Change.session_id == session_id, Change.git_status.is_not(None))):
            ch.git_status = _reconcile(ch, db)
        db.commit()


def _reconcile(ch: Change, db: Any) -> str:
    """committed | uncommitted | reverted, checked against the repo now."""
    root = None
    if ch.project_id and (p := db.get(Project, ch.project_id)):
        root = p.root_path
    if not root:
        return ch.git_status or "uncommitted"
    paths_ = [f.path for f in db.scalars(select(ChangeFile).where(ChangeFile.change_id == ch.id))]
    dirty = set((gitutil.run(root, "diff", "--name-only", "HEAD") or "").split()) | set(
        (gitutil.run(root, "ls-files", "--others", "--exclude-standard") or "").split())
    if any(p in dirty for p in paths_):
        return "uncommitted"
    head = (gitutil.run(root, "rev-parse", "HEAD") or "").strip()
    return "committed" if head and head != ch.git_head_before else "reverted"


def _expand(p: str) -> str:
    return os.path.expanduser(p)


def _user_id() -> str:
    from .identity import user_id

    return user_id()


def inventory(project_id: str | None) -> list[dict[str, Any]]:
    f = paths.home() / "cache" / f"inventory-{project_id or 'none'}.json"
    try:
        data: list[dict[str, Any]] = json.loads(f.read_text())
        return data
    except (OSError, ValueError):
        return []


def _sync_inventory(db: Any, project_id: str | None) -> None:
    now = spool.now()
    for s in inventory(project_id):
        row = db.get(Skill, s["id"])
        if row is None:
            row = Skill(id=s["id"], first_seen=now)
            db.add(row)
        row.kind, row.origin, row.path = s["kind"], s["origin"], s["path"]
        row.description, row.allowed_tools, row.last_seen = s["description"], s["allowed_tools"], now
        if s["kind"] == "project":
            row.scope_project_id = project_id
        if db.get(SkillVersion, (s["id"], s["hash"])) is None:
            db.add(SkillVersion(skill_id=s["id"], hash=s["hash"], first_seen=now))
    db.flush()


def _write_invocations(db: Any, cid: str, invs: list[Invocation]) -> None:
    db.execute(delete(SkillInvocation).where(SkillInvocation.change_id == cid))
    now = spool.now()
    for i, inv in enumerate(invs, start=1):
        if db.get(Skill, inv.skill_id) is None:  # not in any scanned folder: sideloaded
            db.add(Skill(id=inv.skill_id, kind=inv.kind, first_seen=now, last_seen=now))
        db.add(SkillInvocation(change_id=cid, ordinal=i, skill_id=inv.skill_id, hash=inv.hash, trigger=inv.trigger))
    db.flush()
