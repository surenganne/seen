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
         "-c", f"core.attributesFile={os.devnull}", "-c", "submodule.recurse=false",
         "-c", "diff.ignoreSubmodules=all", "-c", "status.submoduleSummary=false"]
_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_ATTR_NOSYSTEM": "1"}


def _raw(cwd: str | Path, args: list[str], timeout: float) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, **_ENV})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


@lru_cache(maxsize=1)
def _git_version() -> str:
    try:
        return subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _supports_attr_source(version: str) -> bool:
    import re

    m = re.search(r"(\d+)\.(\d+)", version)
    if m is None:
        return False
    return (int(m.group(1)), int(m.group(2))) >= (2, 40)


@lru_cache(maxsize=64)
def filter_overrides(cwd: str) -> tuple[str, ...]:
    """Two layers: read attributes from the empty tree (no in-repo .gitattributes can pick a
    driver), and replace every configured filter driver with identity cat anyway."""
    args: list[str] = []
    # --attr-source needs git 2.40+; older git would reject every call. The driver overrides below still apply.
    empty = (_raw(cwd, [*_SAFE, "hash-object", "-t", "tree", os.devnull], 5) or "").strip() \
        if _supports_attr_source(_git_version()) else ""
    if empty:
        args += ["--attr-source", empty]
    out = _raw(cwd, [*_SAFE, "config", "-z", "--name-only", "--get-regexp", r"^filter\."], 5) or ""
    names = {k[len("filter."):k.rindex(".")] for k in out.split("\0") if k.startswith("filter.") and k.count(".") >= 2}
    for n in sorted(names):
        args += ["-c", f"filter.{n}.clean=cat", "-c", f"filter.{n}.smudge=cat",
                 "-c", f"filter.{n}.process=", "-c", f"filter.{n}.required=false"]
    return tuple(args)


def run(cwd: str | Path, *args: str, timeout: float = 10) -> str | None:
    if args and args[0] == "diff":
        args = ("diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=all", *args[1:])
    return _raw(cwd, [*_SAFE, *filter_overrides(str(cwd)), *args], timeout)
