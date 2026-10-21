"""Erase ledger data for DPDP retention and erasure requests. The audit trail is append-only: it is never edited,
a `ledger.purge` event records who erased what (counts only). Ledger bytes are overwritten (secure_delete) and the
file is vacuumed, so a deleted prompt does not linger in free pages."""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from . import audit
from .db import ledger_engine, ledger_session
from .db.models import (
    Change,
    ChangeFile,
    Outbox,
    PiiFinding,
    PolicyResult,
    Project,
    Session,
    SkillInvocation,
)

CHILDREN = (ChangeFile, SkillInvocation, PolicyResult, PiiFinding)


def _run(db: sa.orm.Session, stmt: sa.Delete) -> int:
    return int(db.execute(stmt).rowcount)  # type: ignore[attr-defined]  # DML results are CursorResult


def _purge_outbox(db: sa.orm.Session, before: str | None, project: str | None, everything: bool) -> int:
    """Queued sync payloads hold the same data as the ledger rows, so they must go too or the next sync resurrects it.
    A batch that carries any change of the purged project is dropped whole; unsent changes of other projects in it
    are queued again by the next sync (a change is only marked synced when its batch is acknowledged)."""
    scope = [Outbox.created_at < before] if before else []
    if everything or (before and not project):
        return _run(db, sa.delete(Outbox).where(*scope))
    ids = []
    for o in db.scalars(sa.select(Outbox).where(*scope)):
        try:
            body = json.loads(json.loads(o.payload_json or "{}").get("_body") or "{}")
            hit = any(c.get("project_id") == project for c in body.get("changes", []))
        except (ValueError, AttributeError, TypeError):
            hit = True  # unreadable payload: erase rather than keep what cannot be checked
        if hit:
            ids.append(o.id)
    return sum(_run(db, sa.delete(Outbox).where(Outbox.id.in_(ids[i:i + 500]))) for i in range(0, len(ids), 500))


def _chunks(ids: Sequence[str], n: int = 500) -> list[Sequence[str]]:
    return [ids[i:i + n] for i in range(0, len(ids), n)]


def purge(*, before: str | None = None, project: str | None = None, everything: bool = False, actor: str,
          dry_run: bool = False) -> dict[str, int]:
    """before: ISO date/time, erases changes and sessions that started earlier. project: one project id.
    everything: the whole ledger. Skills inventory and policies are not personal data and stay."""
    if not (before or project or everything):
        raise ValueError("give before, project or everything")
    res: dict[str, int] = {}
    with ledger_session() as db:
        db.execute(sa.text("PRAGMA secure_delete=ON"))
        scope = []
        if project:
            scope.append(Change.project_id == project)
        if before:
            scope.append(Change.started_at < before)
        ids = list(db.scalars(sa.select(Change.id).where(*scope)))
        res["changes"] = len(ids)
        for model in CHILDREN:
            res[model.__tablename__] = 0
            for part in _chunks(ids):
                res[model.__tablename__] += _run(db, sa.delete(model).where(model.change_id.in_(part)))
        for part in _chunks(ids):
            db.execute(sa.delete(Change).where(Change.id.in_(part)))
        sscope = []
        if project:
            sscope.append(Session.project_id == project)
        if before:
            sscope.append(Session.started_at < before)
        res["sessions"] = _run(db, sa.delete(Session).where(*sscope))
        res["projects"] = 0
        if project and not before or everything:
            res["projects"] = _run(db, sa.delete(Project).where(*([Project.id == project] if project else [])))
        res["outbox"] = _purge_outbox(db, before, project, everything)
        if dry_run:
            db.rollback()
            return res
        db.commit()
    audit.append([{"type": "ledger.purge", "actor_kind": "user", "actor_id": actor, "project_id": project,
                   "subject": "everything" if everything else (project or "before"), "outcome": "ok",
                   "detail": {**res, "before": before or "", "scope": "everything" if everything else "partial"}}])
    with ledger_engine().connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.exec_driver_sql("VACUUM")
        c.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    return res
