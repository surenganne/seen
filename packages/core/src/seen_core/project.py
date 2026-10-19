"""Project identity from git (plan 9.1). Stdlib only: runs in hooks."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import gitutil


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    remote: str | None
    root: str  # main checkout (shared by all worktrees)
    worktree: str = ""  # this checkout: where .seen/* and the files being edited live


def _git(cwd: str | Path, *args: str) -> str | None:
    out = gitutil.run(cwd, *args, timeout=5)
    return out.strip() if out is not None else None


def normalise_remote(url: str) -> str:
    u = url.strip().lower()
    u = re.sub(r"^[a-z+]+://", "", u)  # scheme
    u = re.sub(r"^[^@/]+@", "", u)  # credentials or ssh user
    m = re.match(r"^([^/:]+):(?!\d+/)(.*)$", u)  # scp-style host:path (not host:port/)
    if m:
        u = f"{m.group(1)}/{m.group(2)}"
    u = u.rstrip("/")
    return u[:-4] if u.endswith(".git") else u


def resolve_project(cwd: str | Path) -> Project | None:
    if _git(cwd, "rev-parse", "--is-inside-work-tree") != "true":
        return None
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    top = _git(cwd, "rev-parse", "--show-toplevel") or str(cwd)
    # all worktrees share one common dir; its parent is the main checkout
    main_root = os.path.realpath(Path(common).parent) if common else os.path.realpath(top)
    remote_url = _git(cwd, "config", "--get", "remote.origin.url")
    remote = normalise_remote(remote_url) if remote_url else None
    key = remote or main_root
    name = (remote.rsplit("/", 1)[-1] if remote else Path(main_root).name) or "project"
    return Project(id=hashlib.sha1(key.encode()).hexdigest()[:12], name=name, remote=remote, root=main_root,
                   worktree=os.path.realpath(top))
