"""Blocks plus what the ledger knows about the change behind each. Never carries line text or the prompt itself."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa

from ..db.models import Change, ChangeFile, SkillInvocation
from ..headline import headline_of, request_line
from .blame import Block

CHUNK = 900  # SQLite allows 999 variables per statement


@dataclass(frozen=True)
class EnrichedBlock:
    start: int
    end: int
    who: str
    change_id: str | None
    headline: str | None
    started_at: str | None
    model: str | None
    skills: list[str]
    pii_state: str | None


def enrich_blocks(db: Any, blocks: list[Block]) -> list[EnrichedBlock]:
    """Three queries per chunk of 900 ids (changes, files, skills). Local scale: the id list stays short
    (one id per agent block), so the `IN` lists are bounded by CHUNK and nothing is paged beyond that."""
    ids = sorted({b.change_id for b in blocks if b.change_id})
    changes: dict[str, Change] = {}
    files: dict[str, list[str]] = {i: [] for i in ids}
    skills: dict[str, list[str]] = {i: [] for i in ids}
    for chunk in (ids[i:i + CHUNK] for i in range(0, len(ids), CHUNK)):
        changes.update({c.id: c for c in db.scalars(sa.select(Change).where(Change.id.in_(chunk)))})
        for cid, path in db.execute(sa.select(ChangeFile.change_id, ChangeFile.path).where(ChangeFile.change_id.in_(chunk))
                                    .order_by(ChangeFile.path)):
            files[cid].append(path)
        for cid, sk in db.execute(sa.select(SkillInvocation.change_id, SkillInvocation.skill_id)
                                  .where(SkillInvocation.change_id.in_(chunk)).order_by(SkillInvocation.ordinal)):
            if sk:
                skills[cid].append(sk)
    out = []
    for b in blocks:
        c = changes.get(b.change_id or "")
        out.append(EnrichedBlock(
            b.start, b.end, b.who, b.change_id,
            headline_of(c.summary, request_line(c.prompt_text), files[c.id]) if c else None,
            c.started_at if c else None, c.model if c else None, skills[c.id] if c else [], c.pii_state if c else None))
    return out
