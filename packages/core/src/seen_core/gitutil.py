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
         "-c", "diff.ignoreSubmodules=all", "-c", "status.submoduleSummary=false", "-c", "core.quotePath=false",
         "-c", "blame.ignoreRevsFile=", "-c", "i18n.logOutputEncoding=UTF-8", "-c", "i18n.commitEncoding=UTF-8"]
_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_ATTR_NOSYSTEM": "1"}


def _raw(cwd: str | Path, args: list[str], timeout: float) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="surrogateescape", env={**os.environ, **_ENV})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


EMPTY_TREE = {"sha1": "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
              "sha256": "6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321"}


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


def _git_dir(cwd: str) -> Path | None:
    """Find the repo's config dir without spawning git (worktrees resolve to the common dir)."""
    d = Path(os.path.abspath(cwd))
    for p in [d, *d.parents]:
        g = p / ".git"
        if g.is_dir():
            return g
        if g.is_file():
            try:
                target = Path(g.read_text().split("gitdir:", 1)[1].strip())
                target = target if target.is_absolute() else (p / target)
                common = target / "commondir"
                return (target / common.read_text().strip()).resolve() if common.exists() else target
            except (OSError, IndexError):
                return None
    return None


def _cache_key(gd: Path) -> list[object]:
    home = Path.home()
    files = [gd / "config", home / ".gitconfig", Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "git" / "config"]
    import shutil

    exe = shutil.which("git") or "git"
    try:
        est = os.stat(exe)
        key: list[object] = [2, exe, est.st_mtime_ns, est.st_size]  # 2: override set version; a git upgrade changes this too
    except OSError:
        key = [2, exe]
    for f in files:
        try:
            st = f.stat()
            key += [str(f), st.st_mtime_ns, st.st_size]
        except OSError:
            key += [str(f), None]
    return key


@lru_cache(maxsize=64)
def filter_overrides(cwd: str) -> tuple[str, ...]:
    """Cached on disk per repo, keyed on git config mtimes: each hook is a fresh process.
    ponytail: [include] files are not in the key; a filter added via an included file needs a repo config touch."""
    import hashlib
    import json

    from . import paths

    gd = _git_dir(cwd)
    if gd is None:
        return _compute_overrides(cwd)
    f = paths.home() / "cache" / f"git-{hashlib.sha1(str(gd).encode()).hexdigest()[:16]}.json"
    key = _cache_key(gd)
    try:
        hit = json.loads(f.read_text())
        if hit.get("key") == key:
            return tuple(hit["overrides"])
    except (OSError, ValueError, AttributeError):
        pass
    out = _compute_overrides(cwd)
    try:
        paths.ensure_dir(f.parent)
        f.write_text(json.dumps({"key": key, "overrides": list(out)}))
    except OSError:
        pass
    return out


def _compute_overrides(cwd: str) -> tuple[str, ...]:
    """Two layers: read attributes from the empty tree (no in-repo .gitattributes can pick a
    driver), and replace every configured filter driver with identity cat anyway."""
    args: list[str] = []
    # --attr-source needs git 2.40+; older git would reject every call. The driver overrides below still apply.
    empty = EMPTY_TREE.get((_raw(cwd, [*_SAFE, "rev-parse", "--show-object-format"], 5) or "sha1").strip(), "") \
        if _supports_attr_source(_git_version()) else ""
    if empty:
        args += ["--attr-source", empty]
    out = _raw(cwd, [*_SAFE, "config", "-z", "--name-only", "--get-regexp", r"^filter\."], 5) or ""
    names = {k[len("filter."):k.rindex(".")] for k in out.split("\0") if k.startswith("filter.") and k.count(".") >= 2}
    for n in sorted(names):
        args += ["-c", f"filter.{n}.clean=cat", "-c", f"filter.{n}.smudge=cat",
                 "-c", f"filter.{n}.process=", "-c", f"filter.{n}.required=false"]
    out = _raw(cwd, [*_SAFE, "config", "-z", "--name-only", "--get-regexp", r"^diff\."], 5) or ""
    for n in sorted({k[len("diff."):k.rindex(".")] for k in out.split("\0") if k.startswith("diff.") and k.count(".") >= 2}):
        args += ["-c", f"diff.{n}.textconv=", "-c", f"diff.{n}.command="]  # .git/info/attributes can still pick a driver
    return tuple(args)


def run_raw(cwd: str | Path, *args: str, timeout: float = 10) -> str | None:
    """Like run, without newline translation: a lone CR stays inside its line (blame output, blob text)."""
    try:
        r = subprocess.run(_argv(cwd, args), cwd=cwd, capture_output=True, timeout=timeout, env={**os.environ, **_ENV})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.decode("utf-8", errors="surrogateescape") if r.returncode == 0 else None


def _argv(cwd: str | Path, args: tuple[str, ...]) -> list[str]:
    if args and args[0] == "diff":
        args = ("diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=all", *args[1:])
    return ["git", *_SAFE, *filter_overrides(str(cwd)), *args]


def run(cwd: str | Path, *args: str, timeout: float = 10) -> str | None:
    return _raw(cwd, _argv(cwd, args)[1:], timeout)


def run_many(cwd: str | Path, calls: list[tuple[str, ...]], timeout: float = 10) -> list[str | None]:
    """Run several hardened git commands in parallel (each hook is latency-bound)."""
    procs: list[subprocess.Popen[str] | None] = []
    for args in calls:
        try:
            procs.append(subprocess.Popen(_argv(cwd, args), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                          text=True, encoding="utf-8", errors="surrogateescape", env={**os.environ, **_ENV}))
        except OSError:
            procs.append(None)
    out: list[str | None] = []
    for p in procs:
        if p is None:
            out.append(None)
            continue
        try:
            so, _ = p.communicate(timeout=timeout)
            out.append(so if p.returncode == 0 else None)
        except subprocess.TimeoutExpired:
            p.kill()
            out.append(None)
    return out
