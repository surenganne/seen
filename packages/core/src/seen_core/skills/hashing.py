"""Skill folder hash (plan 9.5). Stdlib only."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__"}
SKIP_FILES = {".DS_Store"}


def files(folder: Path) -> list[tuple[str, Path]]:
    root = os.path.realpath(folder)
    out: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d)))
        for f in filenames:
            if f in SKIP_FILES:
                continue
            p = Path(dirpath) / f
            real = os.path.realpath(p)
            if not (real == root or real.startswith(root + os.sep)) or not os.path.isfile(real):
                continue  # never follow links out of the folder
            out.append((p.relative_to(folder).as_posix(), p))
    return sorted(out)


def signature(folder: Path) -> str:
    """Cheap change detector: names, sizes, mtimes. No content reads."""
    h = hashlib.sha1()
    for rel, p in files(folder):
        st = p.stat()
        h.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def hash_folder(folder: Path) -> str:
    h = hashlib.sha256()
    for rel, p in files(folder):
        h.update(f"{rel}\0{hashlib.sha256(p.read_bytes()).hexdigest()}\n".encode())
    return h.hexdigest()
