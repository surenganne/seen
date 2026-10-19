"""Memory files (plan section 10): one memory per markdown file with front matter. Stdlib only.

Team memory: <repo>/.seen/memory/*.md (committed). Personal: ~/.seen/memory/<project_id>/*.md.
Archived files move to <folder>/archive/ and are never injected.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..frontmatter import parse

TYPES = ("decision", "convention", "gotcha", "context")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
# repo-relative, no traversal, printable: a file_ref ends up in the model context and in terminals
REF_RE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._@+-][A-Za-z0-9._@+/ -]{0,299}$")
CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
MAX_BYTES = 64 * 1024


@dataclass
class Memory:
    id: str
    type: str
    body: str
    file_ref: str | None
    verified_at: str | None
    scope: str  # team | personal
    path: str
    source_change: str | None = None
    ok: bool = True
    error: str = ""
    stale: bool = False
    stale_reason: str | None = None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(f"{self.type}\n{self.file_ref}\n{self.body}".encode()).hexdigest()[:16]


def _bad(path: Path, scope: str, error: str, id_: str = "") -> Memory:
    safe = id_ if ID_RE.match(id_ or "") else CTRL.sub("", path.stem)[:80]
    return Memory(id=safe, type="", body="", file_ref=None, verified_at=None, scope=scope, path=str(path), ok=False, error=error)


def _valid_ts(v: str) -> bool:
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def parse_file(path: Path, scope: str) -> Memory:
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_BYTES:
            return _bad(path, scope, "not a regular file under 64 KB")
        with open(path, "rb") as f:
            text = f.read(MAX_BYTES).decode("utf-8", errors="replace")
    except OSError as e:
        return _bad(path, scope, f"unreadable ({type(e).__name__})")
    fm, body = parse(text)
    if not fm:
        return _bad(path, scope, "missing front matter")
    mid = str(fm.get("id") or "")
    if not ID_RE.match(mid):
        return _bad(path, scope, "id missing or invalid (lowercase letters, digits, . _ -)", mid)
    typ = str(fm.get("type") or "")
    if typ not in TYPES:
        return _bad(path, scope, f"type must be one of {', '.join(TYPES)}", mid)
    va = str(fm.get("verified_at") or "") or None
    if va and not _valid_ts(va):
        return _bad(path, scope, "verified_at is not an ISO timestamp", mid)
    if not body.strip():
        return _bad(path, scope, "empty body", mid)
    ref = str(fm.get("file_ref") or "") or None
    if ref and not REF_RE.match(ref):
        return _bad(path, scope, "file_ref must be a repo-relative path", mid)
    src = str(fm.get("source_change") or "") or None
    if src and (CTRL.search(src) or len(src) > 80):
        return _bad(path, scope, "source_change is invalid", mid)
    return Memory(id=mid, type=typ, body=body.strip() + "\n", file_ref=ref, verified_at=va, scope=scope, path=str(path), source_change=src)


def _folder(d: Path | None, scope: str) -> list[Memory]:
    if d is None or not d.is_dir() or d.is_symlink():
        return []
    return [parse_file(p, scope) for p in sorted(d.glob("*.md")) if not p.is_symlink()]


def team_dir(root: str | Path) -> Path:
    return Path(root) / ".seen" / "memory"


def load(root: str | Path | None, personal: Path | None) -> list[Memory]:
    """All memories, invalid ones included with ok=False. Duplicate ids: the second is flagged."""
    out: list[Memory] = []
    seen: set[str] = set()
    for m in _folder(team_dir(root) if root else None, "team") + _folder(personal, "personal"):
        if m.ok and m.id in seen:
            m.ok, m.error = False, f"duplicate id {m.id}"
        if m.ok:
            seen.add(m.id)
        out.append(m)
    return sorted(out, key=lambda m: (not m.ok, m.id))


def _render(fm: dict[str, str | None], body: str) -> str:
    for k, v in fm.items():
        if v is not None and CTRL.search(str(v)):
            raise ValueError(f"front matter value for {k} contains control characters")
    lines = ["---"] + [f"{k}: {v or ''}".rstrip() for k, v in fm.items()] + ["---", body.strip(), ""]
    return "\n".join(lines)


def new_memory(folder: Path, *, id: str, type: str, body: str, file_ref: str | None, source_change: str | None = None) -> Path:
    if not ID_RE.match(id) or type not in TYPES or not body.strip():
        raise ValueError("invalid memory: check id, type and body")
    if file_ref and not REF_RE.match(file_ref):
        raise ValueError("file_ref must be a repo-relative path")
    from .. import safeio

    p = folder / f"{id}.md"
    if p.exists():
        raise FileExistsError(p)
    safeio.write_text(p, _render({"id": id, "type": type, "file_ref": file_ref, "source_change": source_change,
                                  "verified_at": None}, body), folder.parent.parent if folder.name == "memory" else folder)
    return p


def _rewrite(path: Path, **changes: str | None) -> None:
    from .. import safeio

    # root is the repo (like new_memory): a symlinked .seen or .seen/memory is refused before anything is read or written
    root = path.parent.parent.parent if path.parent.name == "memory" else path.parent
    safeio.check_no_symlinks(path, root)
    text = path.read_text()
    fm, body = parse(text)
    fm.update(changes)
    safeio.write_text(path, _render({k: (None if v is None else str(v)) for k, v in fm.items()}, body), root)


def verify(path: Path, now: str) -> None:
    _rewrite(path, verified_at=now)


def archive(path: Path) -> Path:
    from .. import safeio

    dest = path.parent / "archive" / path.name
    safeio.check_no_symlinks(dest, path.parent)
    dest.parent.mkdir(exist_ok=True)
    os.replace(path, dest)
    return dest
