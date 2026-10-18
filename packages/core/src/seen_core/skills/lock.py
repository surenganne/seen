"""<repo>/.seen/skills.lock.json: approved short hashes and blocked skills. Stdlib only."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .. import safeio


@dataclass
class Lockfile:
    approved: dict[str, list[str]] = field(default_factory=dict)
    blocked: list[str] = field(default_factory=list)


def path(root: str | Path) -> Path:
    return Path(root) / ".seen" / "skills.lock.json"


class LockfileError(ValueError):
    pass


def _parse(text: str) -> Lockfile:
    d = json.loads(text)
    approved, blocked = d.get("approved", {}), d.get("blocked", [])
    if not isinstance(approved, dict) or not isinstance(blocked, list) or \
            not all(isinstance(v, list) and all(isinstance(h, str) for h in v) for v in approved.values()) or \
            not all(isinstance(b, str) for b in blocked):
        raise LockfileError("skills.lock.json: unexpected shape")
    return Lockfile(approved={str(k): list(v) for k, v in approved.items()}, blocked=list(blocked))


def load(root: str | Path) -> Lockfile:
    """Lenient read for status display. Writers use load_strict."""
    try:
        return _parse(path(root).read_text())
    except (OSError, ValueError, TypeError, AttributeError):
        return Lockfile()


def load_strict(root: str | Path) -> Lockfile:
    p = path(root)
    safeio.check_no_symlinks(p, Path(root))
    if not p.exists():
        return Lockfile()
    try:
        return _parse(p.read_text())
    except (ValueError, TypeError, AttributeError) as e:
        raise LockfileError(f"{p} is not valid; fix it by hand before approving or blocking ({e})") from e


def _norm(name: str) -> str:
    return name.strip().lstrip("/").strip().lower()


def is_blocked(lk: Lockfile, name: str) -> bool:
    """Match every alias: '/Name', bare vs plugin-qualified ('plug:skill' blocks 'skill' and vice versa).
    Fails closed: a bare blocked name also blocks any plugin's skill of that name."""
    n = _norm(name)
    if not n:
        return False
    for b in (_norm(x) for x in lk.blocked):
        if n == b or n.rsplit(":", 1)[-1] == b or b.rsplit(":", 1)[-1] == n:
            return True
    return False


def status(lk: Lockfile, skill_id: str, full_hash: str | None) -> str:
    if is_blocked(lk, skill_id):
        return "blocked"
    hashes = lk.approved.get(skill_id) or []
    if full_hash and any(full_hash.startswith(h) for h in hashes):
        return "approved"
    return "changed" if hashes else "unreviewed"


def _save(root: str | Path, lk: Lockfile) -> None:
    safeio.write_text(path(root), json.dumps({"approved": dict(sorted(lk.approved.items())),
                                              "blocked": sorted(set(lk.blocked))}, indent=2) + "\n", Path(root))




def approve(root: str | Path, skill_id: str, full_hash: str) -> None:
    with safeio.Locked(path(root)):
        _approve(root, skill_id, full_hash)


def _approve(root: str | Path, skill_id: str, full_hash: str) -> None:
    lk = load_strict(root)
    short = full_hash[:7]
    if short not in lk.approved.setdefault(skill_id, []):
        lk.approved[skill_id].append(short)
    _save(root, lk)


def block(root: str | Path, skill_id: str) -> None:
    with safeio.Locked(path(root)):
        _block(root, skill_id)


def _block(root: str | Path, skill_id: str) -> None:
    lk = load_strict(root)
    if skill_id not in lk.blocked:
        lk.blocked.append(skill_id)
    _save(root, lk)


def unblock(root: str | Path, skill_id: str) -> None:
    with safeio.Locked(path(root)):
        _unblock(root, skill_id)


def _unblock(root: str | Path, skill_id: str) -> None:
    lk = load_strict(root)
    lk.blocked = [b for b in lk.blocked if b != skill_id]
    _save(root, lk)
