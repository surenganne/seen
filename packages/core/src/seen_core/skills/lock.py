"""<repo>/.seen/skills.lock.json: approved short hashes and blocked skills. Stdlib only."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Lockfile:
    approved: dict[str, list[str]] = field(default_factory=dict)
    blocked: list[str] = field(default_factory=list)


def path(root: str | Path) -> Path:
    return Path(root) / ".seen" / "skills.lock.json"


def load(root: str | Path) -> Lockfile:
    try:
        d = json.loads(path(root).read_text())
        return Lockfile(approved={str(k): [str(h) for h in v] for k, v in (d.get("approved") or {}).items()},
                        blocked=[str(b) for b in d.get("blocked") or []])
    except (OSError, ValueError, AttributeError):
        return Lockfile()


def status(lk: Lockfile, skill_id: str, full_hash: str | None) -> str:
    if skill_id in lk.blocked:
        return "blocked"
    hashes = lk.approved.get(skill_id) or []
    if full_hash and any(full_hash.startswith(h) for h in hashes):
        return "approved"
    return "changed" if hashes else "unreviewed"


def _save(root: str | Path, lk: Lockfile) -> None:
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"approved": dict(sorted(lk.approved.items())), "blocked": sorted(set(lk.blocked))}, indent=2) + "\n")
    os.replace(tmp, p)


def approve(root: str | Path, skill_id: str, full_hash: str) -> None:
    lk = load(root)
    short = full_hash[:7]
    if short not in lk.approved.setdefault(skill_id, []):
        lk.approved[skill_id].append(short)
    _save(root, lk)


def block(root: str | Path, skill_id: str) -> None:
    lk = load(root)
    if skill_id not in lk.blocked:
        lk.blocked.append(skill_id)
    _save(root, lk)


def unblock(root: str | Path, skill_id: str) -> None:
    lk = load(root)
    lk.blocked = [b for b in lk.blocked if b != skill_id]
    _save(root, lk)
