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
                w.writerow({**{k: e.get(k) for k in COLUMNS}, "detail": json.dumps(e["detail"], sort_keys=True)})
    else:
        with open(out, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, sort_keys=True) + "\n")
    manifest = {"tool": brand.NAME, "tool_version": brand.VERSION, "schema_version": SCHEMA_VERSION, "format": fmt,
                "created_at": spool.now(), "range": {"project": project, "from": date_from, "to": date_to},
                "count": len(events), "first_seq": events[0]["seq"] if events else None,
                "last_seq": events[-1]["seq"] if events else None, "head_hash": v.head, "head_seq": v.head_seq,
                "verification": {"ok": v.ok, "count": v.count, "break_seq": v.break_seq, "reason": v.reason, "at": v.verified_at},
                "anchored": False, **(extra or {})}
    out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    audit.append([{"type": "export.created", "actor_kind": "user", "actor_id": actor, "project_id": project,
                   "subject": out.name, "detail": {"format": fmt, "from": date_from, "to": date_to, "count": len(events),
                                                   "head": v.head, "verified": v.ok}}])
    return out
