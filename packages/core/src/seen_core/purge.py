"""Erase ledger data for DPDP retention and erasure requests. The audit trail is append-only: it is never edited,
a `ledger.purge` event records who erased what (counts only). Ledger bytes are overwritten (secure_delete) and the
file is vacuumed, so a deleted prompt does not linger in free pages."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from . import audit
from .db import ledger_engine, ledger_session
from .db.models import (
    Change,
    ChangeFile,
    ChangeMemory,
    Outbox,
    PiiFinding,
    PolicyResult,
    Project,
    Session,
    SkillInvocation,
)

CHILDREN = (ChangeFile, ChangeMemory, SkillInvocation, PolicyResult, PiiFinding)


def _run(db: sa.orm.Session, stmt: sa.Delete) -> int:
    return int(db.execute(stmt).rowcount)  # type: ignore[attr-defined]  # DML results are CursorResult


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
        res["outbox"] = 0
        if before or everything:  # queued payloads are not project-tagged: cleared by age or wholesale only
            res["outbox"] = _run(db, sa.delete(Outbox).where(*([Outbox.created_at < before] if before else [])))
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
