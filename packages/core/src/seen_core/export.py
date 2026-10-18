"""Audit export (11A rule 6): events plus a manifest. Verification runs before every export."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from . import audit, brand, paths, spool

SCHEMA_VERSION = "1"
COLUMNS = ["seq", "event_id", "occurred_at", "recorded_at", "actor_kind", "actor_id", "project_id", "session_id",
           "change_id", "type", "subject", "outcome", "detail", "prev_hash", "hash"]


def _cell(v: Any) -> Any:
    """Spreadsheet apps execute cells that start with = + - @ (CSV injection): neutralise them."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def export(base: Path, *, project: str | None, date_from: str | None, date_to: str | None, fmt: str, actor: str,
           extra: dict[str, Any] | None = None) -> Path:
    v = audit.verify()
    events = list(reversed(audit.query(project_id=project, date_from=date_from, date_to=date_to, limit=10_000_000)))
    out = base.with_suffix(f".{fmt}")
    paths.ensure_dir(out.parent)
    if fmt == "csv":
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            for e in events:
                w.writerow({k: _cell(x) for k, x in {**{k: e.get(k) for k in COLUMNS}, "detail": json.dumps(e["detail"], sort_keys=True)}.items()})
    else:
        with open(out, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, sort_keys=True) + "\n")
    joined = _write_joined(base, project=project, date_from=date_from, date_to=date_to, fmt=fmt)
    manifest = {"tool": brand.NAME, "tool_version": brand.VERSION, "schema_version": SCHEMA_VERSION, "format": fmt,
                "created_at": spool.now(), "range": {"project": project, "from": date_from, "to": date_to},
                "count": len(events), "first_seq": events[0]["seq"] if events else None,
                "last_seq": events[-1]["seq"] if events else None, "head_hash": v.head, "head_seq": v.head_seq,
                "verification": {"ok": v.ok, "count": v.count, "break_seq": v.break_seq, "reason": v.reason, "at": v.verified_at},
                "anchored": False, "files": {"events": out.name, "changes": joined.name}, **(extra or {})}
    out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    audit.append([{"type": "export.created", "actor_kind": "user", "actor_id": actor, "project_id": project,
                   "subject": out.name, "detail": {"format": fmt, "from": date_from, "to": date_to, "count": len(events),
                                                   "head": v.head, "verified": v.ok}}])
    return out


def _write_joined(base: Path, *, project: str | None, date_from: str | None, date_to: str | None, fmt: str) -> Path:
    """Per change: which skill versions ran (status at run time, who approved that version) and which policies were met."""
    from sqlalchemy import select

    from .db import ledger_session
    from .db.models import Change, Policy, PolicyResult, SkillInvocation, SkillVersion

    rows: list[dict[str, Any]] = []
    with ledger_session() as db:
        q = select(Change).order_by(Change.started_at)
        if project:
            q = q.where(Change.project_id == project)
        if date_from:
            q = q.where(Change.started_at >= date_from)
        if date_to:
            q = q.where(Change.started_at <= date_to + ("T23:59:59Z" if len(date_to) == 10 else ""))
        pols = {p.id: p for p in db.scalars(select(Policy))}
        versions = {(v.skill_id, v.hash): v for v in db.scalars(select(SkillVersion))}
        for c in db.scalars(q):
            skills = []
            for i in db.scalars(select(SkillInvocation).where(SkillInvocation.change_id == c.id).order_by(SkillInvocation.ordinal)):
                v = versions.get((i.skill_id or "", i.hash or ""))
                skills.append({"skill": i.skill_id, "hash": (i.hash or "")[:12] or None, "trigger": i.trigger, "status_at_run": i.status,
                               "approved_by": v.approved_by if v else None, "approved_at": v.approved_at if v else None})
            policies = [{"policy": r.policy_id, "title": pols[r.policy_id].title if r.policy_id in pols else None,
                         "require_skill": pols[r.policy_id].require_skill if r.policy_id in pols else None, "met": bool(r.met)}
                        for r in db.scalars(select(PolicyResult).where(PolicyResult.change_id == c.id))]
            rows.append({"change_id": c.id, "project_id": c.project_id, "session_id": c.session_id, "started_at": c.started_at,
                         "model": c.model, "skills": skills, "policies": policies})
    out = base.parent / f"{base.name}.changes.{fmt}"
    if fmt == "csv":
        cols = ["change_id", "project_id", "started_at", "skill", "skill_hash", "status_at_run", "approved_by", "approved_at",
                "policy", "policy_met"]
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                pairs = [(s, None) for s in r["skills"]] + [(None, p) for p in r["policies"]] or [(None, None)]
                for s, p in pairs:
                    w.writerow({k: _cell(x) for k, x in {"change_id": r["change_id"], "project_id": r["project_id"], "started_at": r["started_at"],
                                "skill": s and s["skill"], "skill_hash": s and s["hash"], "status_at_run": s and s["status_at_run"],
                                "approved_by": s and s["approved_by"], "approved_at": s and s["approved_at"],
                                "policy": p and p["policy"], "policy_met": None if p is None else p["met"]}.items()})
    else:
        with open(out, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, sort_keys=True) + "\n")
    return out
