"""Git snapshots and per-turn file deltas (plan 9.2). Stdlib only: snapshots run in hooks.

A snapshot is the working tree diffed against one base commit, plus untracked files.
The after-snapshot uses the before-HEAD as its base, so commits made during the turn
are still counted. Known limit: lines a human edits during the turn are counted too.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from . import gitutil

MAX_UNTRACKED = 2000
MAX_COUNT_BYTES = 5 * 1024 * 1024

Snapshot = dict[str, Any]


_git = gitutil.run


def _count_lines(p: Path) -> int:
    try:
        st = os.lstat(p)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_COUNT_BYTES:
            return 0  # symlinks, fifos, devices: never follow or read
        with open(p, "rb") as f:
            data = f.read(MAX_COUNT_BYTES + 1)
    except OSError:
        return 0
    if len(data) > MAX_COUNT_BYTES:
        return 0
    if b"\0" in data[:8000]:
        return 0  # binary
    return data.count(b"\n") + (0 if not data or data.endswith(b"\n") else 1)


def snapshot(cwd: str | Path, base: str | None = None) -> Snapshot:
    top = _git(cwd, "rev-parse", "--show-toplevel")
    if top is None:
        return {"head": None, "numstat": {}, "untracked": {}}
    root = Path(top.strip())
    head = (_git(root, "rev-parse", "HEAD") or "").strip() or None
    ref = base or head
    numstat: dict[str, list[int]] = {}
    out = _git(root, "diff", "--numstat", "--no-renames", ref) if ref else _git(root, "diff", "--numstat", "--no-renames", "--cached")
    for ln in (out or "").splitlines():
        parts = ln.split("\t", 2)
        if len(parts) == 3:
            a, r, path = parts
            numstat[path] = [int(a) if a.isdigit() else 0, int(r) if r.isdigit() else 0]
    untracked: dict[str, int] = {}
    for path in (_git(root, "ls-files", "--others", "--exclude-standard") or "").splitlines()[:MAX_UNTRACKED]:
        untracked[path] = _count_lines(root / path)
    return {"head": head, "numstat": numstat, "untracked": untracked}


def _lines(s: Snapshot, path: str) -> tuple[int, int] | None:
    if path in s["numstat"]:
        a, r = s["numstat"][path]
        return a, r
    if path in s["untracked"]:
        return s["untracked"][path], 0
    return None


def delta(before: Snapshot, after: Snapshot, hints: list[str] | None = None,
          root: str | Path | None = None) -> dict[str, tuple[int, int]]:
    """Per path (added, removed) caused during the turn. hints = paths tools touched."""
    out: dict[str, tuple[int, int]] = {}
    for path in set(before["numstat"]) | set(before["untracked"]) | set(after["numstat"]) | set(after["untracked"]):
        bl, al = _lines(before, path), _lines(after, path)
        if al == bl:
            continue
        b, a = bl or (0, 0), al or (0, 0)
        out[path] = (max(0, a[0] - b[0]), max(0, a[1] - b[1]))
    for h in hints or []:
        rel = os.path.relpath(os.path.realpath(h), os.path.realpath(root)) if root and os.path.isabs(h) else h
        if not rel.startswith(".."):
            out.setdefault(rel, (0, 0))
    return out
