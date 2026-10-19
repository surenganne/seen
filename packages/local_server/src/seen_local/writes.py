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
    if (section, key) == ("sync", "server") and value and not _safe_server(value):
        raise HTTPException(422, "sync.server must be an https URL (http only for localhost), with no credentials in it")
    return value


def _safe_server(url: str) -> bool:
    """Sync carries the API key: a page or process that can edit settings must not be able to point it at plain http
    on the internet or at a URL that smuggles credentials."""
    from urllib.parse import urlparse

    if any(ch.isspace() or ord(ch) < 32 for ch in url):
        return False
    try:
        u = urlparse(url)
        host = u.hostname
    except ValueError:
        return False
    if not host or u.username or u.password:
        return False
    return u.scheme == "https" or (u.scheme == "http" and host in ("localhost", "127.0.0.1", "::1"))


def _change_detail(section: str, key: str, old: Any, new: Any) -> dict[str, Any]:
    """Free-text values (user id, server URL) can hold emails or credentials: log a keyed fingerprint, not the value."""
    if EDITABLE[section][key] is str and (section, key) not in ENUMS:
        from seen_core import secret

        return {"key": f"{section}.{key}", "changed": True, "old_fp": secret.keyed(str(old or ""), 12),
                "new_fp": secret.keyed(str(new), 12)}
    return {"key": f"{section}.{key}", "old": old, "new": new}


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
                   "detail": _change_detail(s, k, o, n)} for s, k, o, n in changes]
        audit.append(events or [{"type": "config.changed", "actor_kind": "user", "actor_id": user_id(),
                                 "subject": "settings", "detail": {"key": "settings", "changed": 0}}])
        return S.Ok(detail={"changed": [f"{s}.{k}" for s, k, _, _ in changes]})

    def _memory_root(project: str) -> tuple[str | None, str]:
        from seen_core.db import ledger_session
        from seen_core.db.models import Project

        with ledger_session() as db:
            p = db.get(Project, project)
        if p is None:
            raise HTTPException(404, "project not found")
        return p.root_path, project

    @app.post("/api/memory/{mid}/verify", response_model=S.MemoryOut)
    def memory_verify(mid: str, project: str) -> S.MemoryOut:
        from seen_core.memory import service

        root, pid = _memory_root(project)
        try:
            m = service.do_verify(root, pid, mid, user_id())
        except KeyError:
            raise HTTPException(404, "memory not found") from None
        return S.MemoryOut(id=m.id, type=m.type, scope=m.scope, status=service.status(m), file_ref=m.file_ref,  # type: ignore[arg-type]
                           verified_at=m.verified_at, source_change=m.source_change, stale_reason=m.stale_reason, error=None,
                           body=m.body, path=paths.redact_home(m.path), content_hash=m.content_hash, used_in=0)

    @app.post("/api/memory/{mid}/archive", response_model=S.Ok)
    def memory_archive(mid: str, project: str) -> S.Ok:
        from seen_core.memory import service

        root, pid = _memory_root(project)
        try:
            dest = service.do_archive(root, pid, mid, user_id())
        except KeyError:
            raise HTTPException(404, "memory not found") from None
        return S.Ok(detail={"archived_to": paths.redact_home(str(dest))})

    def _skill_ctx(sid: str, project: str) -> tuple[str, str, str]:
        """(repo root, current full hash, current status) or 404."""
        from sqlalchemy import select

        from seen_core.db import ledger_session
        from seen_core.db.models import Project, Skill, SkillVersion
        from seen_core.skills import lock

        with ledger_session() as db:
            p = db.get(Project, project)
            sk = db.get(Skill, sid)
            v = db.scalars(select(SkillVersion).where(SkillVersion.skill_id == sid).order_by(SkillVersion.first_seen.desc())).first()
        if p is None or not p.root_path or sk is None or v is None:
            raise HTTPException(404, "skill or project not found")
        return p.root_path, v.hash, lock.status(lock.load(p.root_path), sid, v.hash)

    def _record_skill(sid: str, project: str, h: str, old: str, new: str) -> None:
        audit.append([{"type": "approval.skill", "actor_kind": "user", "actor_id": user_id(), "project_id": project,
                       "subject": sid, "detail": {"skill": sid, "hash": h[:12], "old": old, "new": new}}])

    @app.post("/api/skills/{sid}/approve", response_model=S.Ok)
    def skill_approve(sid: str, project: str) -> S.Ok:
        from seen_core.db import ledger_session
        from seen_core.db.models import SkillVersion
        from seen_core.skills import lock

        root, h, old = _skill_ctx(sid, project)
        try:
            lock.unblock(root, sid)
            lock.approve(root, sid, h)
        except lock.LockfileError as e:
            raise HTTPException(409, str(e)) from None
        with ledger_session() as db:
            v = db.get(SkillVersion, (sid, h))
            if v is not None:
                v.approved_by, v.approved_at = user_id(), spool.now()
                db.commit()
        _record_skill(sid, project, h, old, "approved")
        return S.Ok(detail={"status": "approved", "hash": h[:7]})

    @app.post("/api/skills/{sid}/block", response_model=S.Ok)
    def skill_block(sid: str, project: str) -> S.Ok:
        from seen_core.skills import lock

        root, h, old = _skill_ctx(sid, project)
        try:
            lock.block(root, sid)
        except lock.LockfileError as e:
            raise HTTPException(409, str(e)) from None
        _record_skill(sid, project, h, old, "blocked")
        return S.Ok(detail={"status": "blocked"})

    @app.post("/api/pii/{finding_id}/mark-test-data", response_model=S.Ok)
    def pii_mark_test_data(finding_id: str) -> S.Ok:
        from sqlalchemy import select

        from seen_core.db import ledger_session
        from seen_core.db.models import Change, PiiFinding

        with ledger_session() as db:
            f = db.get(PiiFinding, finding_id)
            if f is None:
                raise HTTPException(404, "finding not found")
            old = f.status
            f.status = "test_data"
            db.flush()
            ch = db.get(Change, f.change_id) if f.change_id else None
            if ch is not None:
                ch.pii_count = sum(x.count for x in db.scalars(select(PiiFinding).where(PiiFinding.change_id == ch.id,
                                                                                         PiiFinding.status == "open")))
                if ch.pii_state != "blocked":
                    ch.pii_state = "found" if ch.pii_count else "none"
            pid = ch.project_id if ch else None
            audit.append([{"type": "approval.pii_test_data", "actor_kind": "user", "actor_id": user_id(), "project_id": pid,
                           "change_id": f.change_id, "subject": finding_id,
                           "detail": {"finding": finding_id, "type": f.type, "old": old, "new": "test_data"}}])
            db.commit()
        return S.Ok(detail={"status": "test_data"})

    @app.post("/api/audit/export", response_model=S.ExportOut)
    def post_export(body: S.ExportIn) -> S.ExportOut:
        import json

        name = f"audit-{body.project or 'all'}-{spool.now().replace(':', '').replace('.', '')}"
        out = export.export(paths.home() / "exports" / name, project=body.project, date_from=body.date_from,
                            date_to=body.date_to, fmt=body.format, actor=user_id())
        state.pop("v", None)
        manifest = json.loads(out.with_suffix(".manifest.json").read_text())
        return S.ExportOut(path=paths.redact_home(str(out)), manifest=manifest)
