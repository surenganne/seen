"""Memory operations shared by the CLI and the local API. Every human action is audited."""

from __future__ import annotations

from pathlib import Path

from .. import audit, paths, spool
from .files import Memory, archive, load, new_memory, team_dir, verify
from .stale import mark_stale


def status(m: Memory) -> str:
    if not m.ok:
        return "invalid"
    if m.stale:
        return "stale"
    return "verified" if m.verified_at else "unverified"


def all_memories(root: str | Path | None, project_id: str | None) -> list[Memory]:
    personal = paths.personal_memory_dir(project_id) if project_id else None
    return mark_stale(load(root, personal), project_id)


def find(root: str | Path | None, project_id: str | None, mid: str) -> Memory:
    for m in all_memories(root, project_id):
        if m.ok and m.id == mid:
            return m
    raise KeyError(mid)


def add(root: Path, project_id: str, *, mid: str, type_: str, text: str, file_ref: str | None, personal: bool, actor: str) -> Path:
    folder = paths.ensure_dir(paths.personal_memory_dir(project_id)) if personal else team_dir(root)
    p = new_memory(folder, id=mid, type=type_, body=text, file_ref=file_ref)
    m = find(root, project_id, mid)
    audit.append([{"type": "approval.memory_added", "actor_kind": "user", "actor_id": actor, "project_id": project_id,
                   "subject": mid, "detail": {"memory": mid, "scope": m.scope, "type": type_, "content_hash": m.content_hash}}])
    return p


def do_verify(root: str | Path | None, project_id: str | None, mid: str, actor: str) -> Memory:
    m = find(root, project_id, mid)
    old = status(m)
    verify(Path(m.path), spool.now())
    new = find(root, project_id, mid)
    audit.append([{"type": "approval.memory_verified", "actor_kind": "user", "actor_id": actor, "project_id": project_id,
                   "subject": mid, "detail": {"memory": mid, "old": old, "new": status(new), "content_hash": new.content_hash}}])
    return new


def do_archive(root: str | Path | None, project_id: str | None, mid: str, actor: str) -> Path:
    m = find(root, project_id, mid)
    dest = archive(Path(m.path))
    audit.append([{"type": "approval.memory_archived", "actor_kind": "user", "actor_id": actor, "project_id": project_id,
                   "subject": mid, "detail": {"memory": mid, "old": status(m), "new": "archived", "content_hash": m.content_hash}}])
    return dest
