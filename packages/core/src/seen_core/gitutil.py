"""Hardened git runner. Repo config is untrusted input: hooks run git on every prompt,
so fsmonitor, hooks, external diff/textconv, filter drivers, ssh and lock writes are
switched off. Stdlib only."""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

_SAFE = ["-c", "core.fsmonitor=false", "-c", f"core.hooksPath={os.devnull}", "-c", "diff.external=",
         "-c", "core.pager=cat", "-c", "protocol.allow=never", "-c", "core.sshCommand=false",
         "-c", f"core.attributesFile={os.devnull}"]
_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_ATTR_NOSYSTEM": "1"}


def _raw(cwd: str | Path, args: list[str], timeout: float) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, **_ENV})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


@lru_cache(maxsize=64)
def filter_overrides(cwd: str) -> tuple[str, ...]:
    """Replace every configured filter driver with identity cat (clean/smudge run on diff)."""
    out = _raw(cwd, [*_SAFE, "config", "--get-regexp", r"^filter\."], 5) or ""
    names = {ln.split(" ", 1)[0].split(".")[1] for ln in out.splitlines() if ln.count(".") >= 2}
    args: list[str] = []
    for n in sorted(names):
        args += ["-c", f"filter.{n}.clean=cat", "-c", f"filter.{n}.smudge=cat",
                 "-c", f"filter.{n}.process=", "-c", f"filter.{n}.required=false"]
    return tuple(args)


def run(cwd: str | Path, *args: str, timeout: float = 10) -> str | None:
    if args and args[0] == "diff":
        args = ("diff", "--no-ext-diff", "--no-textconv", *args[1:])
    return _raw(cwd, [*_SAFE, *filter_overrides(str(cwd)), *args], timeout)
