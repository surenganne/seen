"""State-changing routes. Every one writes an audit event (11A rule 3; route-walk test enforces it)."""

from __future__ import annotations

from typing import Any

import tomli_w
from fastapi import FastAPI, HTTPException

from seen_core import audit, config, export, paths, safeio, spool
from seen_core.identity import user_id

from . import schemas as S

ENUMS = {("pii", "mode"): {"off", "report", "warn", "block"}, ("pii", "store_prompt_text"): {"full", "redacted", "off"},
         ("pii", "engine"): {"regex", "presidio"}, ("pii", "min_confidence"): {"low", "medium", "high"}}
EDITABLE = {"memory": {"inject": bool, "gate": bool, "budget_tokens": int}, "skills": {"audit": bool},
            "audit": {"retention_days": int},
            "pii": {"mode": str, "min_confidence": str, "types": list, "scan_tool_results": bool, "scan_diff": bool,
                    "store_prompt_text": str, "engine": str},
            "sync": {"enabled": bool, "server": str, "send_paths": bool, "send_tokens": bool, "send_cost": bool,
                     "send_skills": bool, "send_pii_counts": bool, "send_audit": bool},
            "user": {"id": str}}


def _validate(section: str, key: str, value: Any) -> Any:
    typ = EDITABLE.get(section, {}).get(key)
    if typ is None:
        raise HTTPException(422, f"{section}.{key} is not editable")
    if typ is int and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
        raise HTTPException(422, f"{section}.{key} must be a positive integer")
    if typ is not int and not isinstance(value, typ):
        raise HTTPException(422, f"{section}.{key} must be {typ.__name__}")
    if (section, key) in ENUMS and value not in ENUMS[(section, key)]:
        raise HTTPException(422, f"{section}.{key} must be one of {sorted(ENUMS[(section, key)])}")
    if isinstance(value, str) and len(value) > 200:
        raise HTTPException(422, f"{section}.{key} is too long")
    return value


def register(app: FastAPI, state: dict[str, Any]) -> None:
    @app.put("/api/settings", response_model=S.Ok)
    def put_settings(body: S.SettingsIn) -> S.Ok:
        current = config.load()
        changes = []
        for section, values in body.model_dump(exclude_none=True).items():
            for key, value in values.items():
                value = _validate(section, key, value)
                old = current[section].get(key)
                if old != value:
                    current[section][key] = value
                    changes.append((section, key, old, value))
        if changes:
            on_disk = {k: v for k, v in current.items() if v != config.DEFAULTS.get(k)}
            safeio.write_text(paths.config_toml(), tomli_w.dumps(on_disk), paths.ensure_dir(paths.home()))
        events = [{"type": "config.changed", "actor_kind": "user", "actor_id": user_id(), "subject": f"{s}.{k}",
                   "detail": {"key": f"{s}.{k}", "old": o, "new": n}} for s, k, o, n in changes]
        audit.append(events or [{"type": "config.changed", "actor_kind": "user", "actor_id": user_id(),
                                 "subject": "settings", "detail": {"key": "settings", "changed": 0}}])
        return S.Ok(detail={"changed": [f"{s}.{k}" for s, k, _, _ in changes]})

    @app.post("/api/audit/export", response_model=S.ExportOut)
    def post_export(body: S.ExportIn) -> S.ExportOut:
        import json

        name = f"audit-{body.project or 'all'}-{spool.now().replace(':', '').replace('.', '')}"
        out = export.export(paths.home() / "exports" / name, project=body.project, date_from=body.date_from,
                            date_to=body.date_to, fmt=body.format, actor=user_id())
        state.pop("v", None)
        manifest = json.loads(out.with_suffix(".manifest.json").read_text())
        return S.ExportOut(path=paths.redact_home(str(out)), manifest=manifest)
