"""Hardened git runner. Repo config is untrusted input: hooks run git on every prompt,
so fsmonitor, hooks, external diff drivers and lock writes are switched off. Stdlib only."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_SAFE = ["-c", "core.fsmonitor=false", "-c", f"core.hooksPath={os.devnull}", "-c", "diff.external=",
         "-c", "core.pager=cat", "-c", "protocol.allow=never"]
_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}


def run(cwd: str | Path, *args: str, timeout: float = 10) -> str | None:
    if args and args[0] == "diff":
        args = ("diff", "--no-ext-diff", "--no-textconv", *args[1:])
    try:
        r = subprocess.run(["git", *_SAFE, *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, **_ENV})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None
