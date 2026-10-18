"""Spool + transcript + git -> ledger rows. Runs at Stop and SessionEnd (not the hot path)."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select

from . import audit, gitdelta, gitutil, paths, policy, pricing, spool
from .db import ledger_session
from .db.models import (
    Change,
    ChangeFile,
    ChangeMemory,
    Policy,
    PolicyResult,
    Project,
    Session,
    Skill,
    SkillInvocation,
    SkillVersion,
)
from .hook import EDIT_TOOLS
from .identity import user_id as _uid
from .invocations import Invocation, reconcile
from .skills import lock
from .skills.scan import TRUST
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
        _write_memories(db, cid, session_id, lines, turn_lines)
        _sync_inventory(db, pid)
        db.execute(delete(ChangeFile).where(ChangeFile.change_id == cid))
        for path, (a, r) in sorted(files.items()):
            db.add(ChangeFile(change_id=cid, path=path, added=a, removed=r))
        invs = reconcile(turn_lines, t, "/" + ts["slash"] if ts.get("slash") else "", {s["id"]: s for s in inventory(pid)})
        root = start.get("root")
        lk = lock.load(root) if root else lock.Lockfile()
        for inv in invs:
            inv.status = lock.status(lk, inv.skill_id, inv.hash)
        _write_invocations(db, cid, invs)
        pols = policy.load(root)
        results = policy.evaluate(pols, sorted(files), {i.skill_id for i in invs})
        _write_policies(db, cid, pid, pols, results)
        db.commit()
    audit_spool(session_id)
    ev = _ctx(session_id, pid, cid)
    audit.append(_fresh([
        *[{**ev, "event_id": f"{cid}:skill:{i}", "type": "skill.invoked", "actor_kind": "agent", "subject": inv.skill_id,
           "detail": {"skill": inv.skill_id, "hash": (inv.hash or "")[:12] or None, "trigger": inv.trigger, "status": inv.status}}
          for i, inv in enumerate(invs, 1)],
        *[{**ev, "event_id": f"{cid}:file:{path}", "type": "file.changed", "actor_kind": "agent", "subject": path,
           "detail": {"path": path, "added": a, "removed": r}} for path, (a, r) in sorted(files.items())],
        {**ev, "event_id": f"{cid}:turn.end", "type": "turn.end", "actor_kind": "agent",
         "detail": {"tok_in": _sum(t, "tok_in"), "tok_out": _sum(t, "tok_out"), "tok_cache_read": _sum(t, "tok_cache_read"),
                    "tok_cache_write": _sum(t, "tok_cache_write"), "cost_usd": cost, "price_version": price_version,
                    "head_before": before["head"] if before else None, "head_after": head_after, "files": len(files)}},
    ]))
    audit.append(_fresh([{**ev, "event_id": f"{cid}:policy:{pol_id}", "type": "policy.result", "actor_kind": "system",
                          "subject": pol_id, "outcome": "ok" if met else "failed", "detail": {"policy": pol_id, "met": met}}
                         for pol_id, met in results]))
    missed = [p for p in pols if p.mode == "enforce" and (p.id, False) in results]
    return {"change_id": cid, "files": sorted(files), "turn": t, "turn_lines": turn_lines, "session_start": start,
            "invocations": invs, "policy_results": results,
            "block_reason": policy.block_reason(missed[0], sorted(files)) if missed else None}


def finish_session(session_id: str) -> None:
    audit_spool(session_id)
    audit.record_head()
    sweep_incomplete()
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
        elif TRUST.get(row.kind or "", 0) > TRUST.get(s["kind"], 0):
            continue  # never let a lower-trust folder take over a known skill id
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
        db.add(SkillInvocation(change_id=cid, ordinal=i, skill_id=inv.skill_id, hash=inv.hash, trigger=inv.trigger, status=inv.status))
    db.flush()


# ---- spool -> audit chain (plan 11A rule 2: hooks never write the DB, ingest converts in order)

def _ctx(session_id: str, project_id: str | None, change_id: str | None = None) -> dict[str, Any]:
    return {"actor_id": _uid(), "session_id": session_id, "project_id": project_id, "change_id": change_id}


def _clip(v: Any) -> Any:
    if isinstance(v, str) and len(v) > audit.MAX_STR:
        return "…" + v[-(audit.MAX_STR - 1):]  # keep the tail: file names live there
    if isinstance(v, dict):
        return {k: _clip(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clip(x) for x in v]
    return v


def _norm(e: dict[str, Any]) -> dict[str, Any]:
    """Make an event fit the audit limits instead of losing the batch."""
    out = _clip(e)
    if len(e["event_id"]) > audit.MAX_STR:
        out["event_id"] = "h:" + hashlib.sha256(e["event_id"].encode()).hexdigest()
    return dict(out)


def _fresh(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise, then drop events already in the chain (deterministic ids: re-ingest is idempotent)."""
    events = [_norm(e) for e in events]
    ids = [e["event_id"] for e in events]
    if not ids:
        return []
    c = audit.connect()
    try:
        have = {r[0] for r in c.execute(f"SELECT event_id FROM audit_events WHERE event_id IN ({','.join('?' * len(ids))})", ids)}
    finally:
        c.close()
    return [e for e in events if e["event_id"] not in have]


def _prev_start(project_id: str | None, session_id: str) -> dict[str, Any] | None:
    for e in audit.query(project_id=project_id, type_="session.start", limit=5):
        if e["session_id"] != session_id:
            return e
    return None


def _events_for(session_id: str, i: int, ln: dict[str, Any], pid: str | None) -> list[dict[str, Any]]:
    ev = {**_ctx(session_id, pid), "event_id": f"{session_id}:{i}", "occurred_at": ln.get("t")}
    kind = ln.get("ev")
    if kind == "session_start":
        out = [{**ev, "type": "session.start", "actor_kind": "system", "subject": ln.get("project_name"),
                "detail": {"plugin_version": ln.get("plugin_version"), "config_hash": ln.get("config_hash"),
                           "lockfile_hash": ln.get("lock_hash"), "policies_hash": ln.get("policies_hash"),
                           "source": ln.get("source")}}]
        prev = _prev_start(pid, session_id)
        if prev:
            for key, typ in (("lockfile_hash", "lockfile.changed"), ("policies_hash", "policies.changed")):
                old, new = prev["detail"].get(key), out[0]["detail"][key]
                if old != new:
                    out.append({**ev, "event_id": f"{session_id}:{i}:{typ}", "type": typ, "actor_kind": "system",
                                "detail": {"old": old, "new": new}})
        return out
    if kind == "turn_start":
        return [{**ev, "type": "turn.start", "actor_kind": "user",
                 "detail": {"prompt_hmac": ln.get("prompt_hmac"), "prompt_len": ln.get("prompt_len"), "slash": ln.get("slash")}}]
    if kind == "tool":
        d = {"tool": ln.get("tool"), "path": ln.get("path"), "cmd0": ln.get("cmd0"), "skill": ln.get("skill")}
        return [{**ev, "type": "tool.call", "actor_kind": "agent", "subject": ln.get("tool"),
                 "detail": {k: v for k, v in d.items() if v is not None}}]
    if kind == "gate":
        return [{**ev, "type": "gate.decision", "actor_kind": "hook", "outcome": "blocked" if ln.get("decision") == "block" else "ok",
                 "subject": ln.get("hook"), "detail": {"hook": ln.get("hook"), "decision": ln.get("decision"), "reason": ln.get("reason")}}]
    if kind == "memory_injected":
        return [{**ev, "type": "memory.injected", "actor_kind": "hook",
                 "detail": {"ids": ln.get("ids"), "hashes": ln.get("hashes"), "tokens": ln.get("tokens")}}]
    if kind == "capture_gap":
        return [{**ev, "type": "capture.gap", "actor_kind": "hook", "outcome": "failed", "subject": ln.get("hook"),
                 "detail": {"hook": ln.get("hook"), "error": ln.get("error")}}]
    if kind == "pii_prompt":
        return [{**ev, "event_id": f"{session_id}:{i}:{n}", "type": "pii.finding", "actor_kind": "hook",
                 "outcome": "blocked" if ln.get("blocked") else "ok",
                 "detail": {"type": f["type"], "count": f["count"], "confidence": f["confidence"], "destination": "model",
                            "source_kind": "prompt"}} for n, f in enumerate(ln.get("findings") or [])]
    if kind == "session_end":
        return [{**ev, "type": "session.end", "actor_kind": "system", "detail": {"reason": ln.get("reason")}}]
    return []  # skill_start, turn_end: summarised by skill.invoked / turn.end


def audit_spool(session_id: str) -> None:
    lines = spool.read(session_id)
    pid = next((ln.get("project_id") for ln in lines if ln.get("ev") == "session_start"), None)
    events = [e for i, ln in enumerate(lines) for e in _events_for(session_id, i, ln, pid)]
    audit.append(_fresh(events))


def sweep_incomplete(max_age_s: float = 6 * 3600) -> None:
    """Sessions that never reached SessionEnd get session.incomplete (the trail records its own gaps)."""
    import time

    d = paths.home() / "spool"
    if not d.is_dir():
        return
    for f in d.glob("*.jsonl"):
        if time.time() - f.stat().st_mtime < max_age_s:
            continue
        sid = f.stem
        lines = spool.read(sid)
        if not lines or any(ln.get("ev") == "session_end" for ln in lines):
            continue
        try:
            audit_spool(sid)
        except Exception:
            continue  # one bad spool must not stop the sweep; it is retried next time
        pid = next((ln.get("project_id") for ln in lines if ln.get("ev") == "session_start"), None)
        last = audit.query(session=sid, limit=1)
        audit.append(_fresh([{**_ctx(sid, pid), "event_id": f"{sid}:incomplete", "type": "session.incomplete",
                              "actor_kind": "system", "outcome": "failed",
                              "detail": {"last_seq": last[0]["seq"] if last else None}}]))


def _write_memories(db: Any, cid: str, session_id: str, lines: list[dict[str, Any]], turn_lines: list[dict[str, Any]]) -> None:
    """Everything injected so far this session is in the model's context for this turn."""
    from .memory import session as msess

    upto = lines[: lines.index(turn_lines[-1]) + 1] if turn_lines and turn_lines[-1] in lines else lines
    injected: dict[str, str] = {}
    for ln in upto:
        if ln.get("ev") == "memory_injected":
            injected.update(zip(ln.get("ids") or [], ln.get("hashes") or [], strict=False))
    starts = [i for i, ln in enumerate(lines) if ln.get("ev") == "turn_start"]
    first_turn = bool(starts) and turn_lines and lines.index(turn_lines[0]) == starts[0]
    window = upto if first_turn else turn_lines
    tokens = sum(int(ln.get("tokens") or 0) for ln in window if ln.get("ev") == "memory_injected")
    db.execute(delete(ChangeMemory).where(ChangeMemory.change_id == cid))
    for mid, h in sorted(injected.items()):
        db.add(ChangeMemory(change_id=cid, memory_id=mid, content_hash=h))
    row = db.get(Change, cid)
    row.mem_state = msess.read(session_id).get("state") or "none"
    row.mem_injected_tokens = tokens


def _write_policies(db: Any, cid: str, pid: str | None, pols: list[policy.Policy], results: list[tuple[str, bool]]) -> None:
    for p in pols:  # mirror the committed file into the ledger for the dashboard
        key = f"{pid}:{p.id}"
        row = db.get(Policy, key) or Policy(id=key)
        row.project_id, row.title, row.paths_json = pid, p.title, json.dumps(p.paths)
        row.require_skill, row.mode = p.require_skill, p.mode
        db.merge(row)
    db.execute(delete(PolicyResult).where(PolicyResult.change_id == cid))
    for pol_id, met in results:
        db.add(PolicyResult(change_id=cid, policy_id=f"{pid}:{pol_id}", met=int(met)))
