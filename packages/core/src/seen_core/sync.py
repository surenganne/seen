"""Team sync serializer (plan principle 4, 11B team sync). Builds what may leave the machine.

Allowlist by construction: each field is added only when its switch is on. Never prompts, summaries,
diffs, file contents, PII values, fingerprints or PII source references.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select

from . import audit, config, paths
from .db import ledger_session
from .db.models import Change, ChangeFile, PiiFinding, PolicyResult, Session, Skill, SkillInvocation


def _change(db: Any, c: Change, s: dict[str, Any]) -> dict[str, Any]:
    sess = db.get(Session, c.session_id) if c.session_id else None
    files = list(db.scalars(select(ChangeFile).where(ChangeFile.change_id == c.id)))
    out: dict[str, Any] = {"id": c.id, "project_id": c.project_id, "session_id": c.session_id, "seq": c.seq,
                           "started_at": c.started_at, "duration_s": c.duration_s, "tool": sess.tool if sess else "claude-code",
                           "user_id": sess.user_id if sess else None, "model": c.model, "git_status": c.git_status,
                           "mem_state": c.mem_state, "file_count": len(files),
                           "lines_added": sum(f.added for f in files), "lines_removed": sum(f.removed for f in files)}
    if s["send_paths"]:
        out["files"] = [{"path": f.path, "added": f.added, "removed": f.removed} for f in files]
    if s["send_tokens"]:
        out.update(tok_in=c.tok_in, tok_out=c.tok_out, tok_cache_read=c.tok_cache_read, tok_cache_write=c.tok_cache_write)
    if s["send_cost"]:
        out.update(cost_usd=c.cost_usd, price_version=c.price_version)
    if s["send_skills"]:
        kinds = dict(db.execute(select(Skill.id, Skill.kind)).all())
        out["skills"] = [{"skill": i.skill_id, "kind": kinds.get(i.skill_id), "hash": i.hash, "trigger": i.trigger, "status": i.status}
                         for i in db.scalars(select(SkillInvocation).where(SkillInvocation.change_id == c.id).order_by(SkillInvocation.ordinal))]
        out["policies"] = [{"policy": p.policy_id, "met": bool(p.met)}
                           for p in db.scalars(select(PolicyResult).where(PolicyResult.change_id == c.id))]
    if s["send_pii_counts"]:
        counts: Counter[str] = Counter()
        for f in db.scalars(select(PiiFinding).where(PiiFinding.change_id == c.id, PiiFinding.status == "open")):
            counts[f.type or "?"] += f.count
        out["pii"] = {"state": c.pii_state, "counts": dict(counts)}
    return out


# Per event type, the detail keys that may leave the machine. Anything else (keyed hashes, ids of
# memory contents, unknown keys) is dropped. Path keys additionally need send_paths.
AUDIT_DETAIL = {
    "session.start": {"plugin_version", "source"}, "session.end": {"reason"}, "session.incomplete": {"last_seq"},
    "capture.gap": {"hook", "error"}, "turn.start": {"prompt_len", "slash"},
    "turn.end": {"tok_in", "tok_out", "tok_cache_read", "tok_cache_write", "cost_usd", "price_version", "files"},
    "memory.injected": {"tokens"}, "gate.decision": {"hook", "decision", "reason"}, "file.changed": {"path", "added", "removed"},
    "tool.call": {"tool", "cmd0", "skill", "path"}, "skill.invoked": {"skill", "hash", "trigger", "status"},
    "policy.result": {"policy", "met"}, "pii.finding": {"type", "count", "confidence", "destination", "source_kind"},
    "pii.allowlisted": {"count", "source_kind"}, "approval.skill": {"skill", "hash", "old", "new"},
    "approval.memory_verified": {"memory", "old", "new"}, "approval.memory_archived": {"memory", "old", "new"},
    "approval.memory_added": {"memory", "scope", "type"}, "approval.pii_test_data": {"type", "old", "new"},
    "config.changed": {"key", "changed"}, "lockfile.changed": set(), "policies.changed": set(),
    "export.created": {"format", "count", "verified"}, "sync.batch": {"kind", "count", "server", "ack"},
    "audit.checkpoint": {"pruned_from_seq", "pruned_to_seq"},
}
PATH_KEYS = {"path"}


def _audit_events(s: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    out = []
    for e in reversed(audit.query(limit=limit)):
        keep = AUDIT_DETAIL.get(e["type"], set()) - (set() if s["send_paths"] else PATH_KEYS)
        d = {k: v for k, v in e["detail"].items() if k in keep}
        out.append({k: e[k] for k in ("seq", "event_id", "occurred_at", "actor_kind", "actor_id", "project_id", "session_id",
                                      "change_id", "type", "outcome", "prev_hash", "hash")} | {"detail": d})
    return out


def heads() -> list[dict[str, Any]]:
    try:
        lines = paths.audit_heads().read_text().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines[-50:]:
        p = ln.split()
        if len(p) >= 3:
            out.append({"at": p[0], "seq": int(p[1]), "hash": p[2]})
    return out


def build_batch(limit: int = 500) -> dict[str, Any]:
    s = config.load()["sync"]
    if not s["enabled"]:
        return {"changes": [], "audit_heads": [], "audit": []}
    with ledger_session() as db:
        rows = list(db.scalars(select(Change).where(Change.synced_at.is_(None)).order_by(Change.started_at).limit(limit)))
        changes = [_change(db, c, s) for c in rows]
    return {"changes": changes, "audit_heads": heads(), "audit": _audit_events(s, limit) if s["send_audit"] else []}
