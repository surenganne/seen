"""Writes into repo-controlled folders. A repo is untrusted: never follow a planted symlink.
Stdlib only."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path

from . import paths


def check_no_symlinks(target: Path, root: Path) -> None:
    """Refuse if target or any folder between root and target is a symlink."""
    root = Path(os.path.abspath(root))
    p = Path(os.path.abspath(target))
    for part in [p, *p.parents]:
        if part == root or root not in part.parents and part != root:
            break
        try:
            if stat.S_ISLNK(os.lstat(part).st_mode):
                raise OSError(f"refusing to write through symlink {part}")
        except FileNotFoundError:
            continue


def write_text(target: Path, text: str, root: Path) -> None:
    """Atomic write: random temp name (O_EXCL), then rename over target."""
    check_no_symlinks(target, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    check_no_symlinks(target, root)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def lock_path(key: str | Path) -> Path:
    """Lock files live under SEEN_HOME, never in the repo."""
    d = paths.ensure_dir(paths.home() / "locks")
    return d / (hashlib.sha1(str(os.path.abspath(key)).encode()).hexdigest()[:16] + ".lock")


class Locked:
    """Exclusive flock on a lock file under SEEN_HOME."""

    def __init__(self, key: str | Path) -> None:
        self.path = lock_path(key)

    def __enter__(self) -> Locked:
        import fcntl

        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc: object) -> None:
        os.close(self.fd)
