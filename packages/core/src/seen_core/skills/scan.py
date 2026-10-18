"""Skill inventory (plan section 11). Stdlib only: runs from the session-start hook.

Hashes are cached per folder by a stat signature, so a rescan only reads files that changed.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import paths
from ..frontmatter import parse
from .hashing import hash_folder, signature

ORG_DIRS = ["/Library/Application Support/ClaudeCode", "/etc/claude-code"]
MAX_MD_BYTES = 1024 * 1024
TRUST = {"org": 5, "user": 4, "plugin": 3, "project": 2, "builtin": 1, "sideload": 0}


def _regular_inside(p: Path, base: Path) -> bool:
    """A regular, non-symlink file whose real path stays under base and is not huge."""
    try:
        st = os.lstat(p)
    except OSError:
        return False
    real = os.path.realpath(p)
    root = os.path.realpath(base)
    return stat.S_ISREG(st.st_mode) and st.st_size <= MAX_MD_BYTES and real.startswith(root + os.sep)


def _read_md(p: Path) -> str:
    with open(p, "rb") as f:
        return f.read(MAX_MD_BYTES).decode("utf-8", errors="replace")


@dataclass(frozen=True)
class SkillEntry:
    id: str
    name: str
    kind: str  # plugin | user | project | org | builtin | sideload
    origin: str | None
    path: str
    description: str | None
    allowed_tools: str | None
    hash: str


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()


def _org_dirs() -> list[Path]:
    env = os.environ.get("SEEN_ORG_SKILLS_DIRS")
    return [Path(p) for p in (env.split(os.pathsep) if env else ORG_DIRS)]


def _cache_file() -> Path:
    return paths.home() / "cache" / "skill-hashes.json"


def _load_cache() -> dict[str, list[str]]:
    try:
        data: dict[str, list[str]] = json.loads(_cache_file().read_text())
        return data
    except (OSError, ValueError):
        return {}


def _candidates(base: Path) -> list[tuple[str, Path, Path]]:
    """(name, folder-or-file to hash, file holding front matter) under a .claude-like root."""
    out = []
    sk = base / "skills"
    if sk.is_dir():
        for d in sorted(sk.iterdir()):
            if d.is_dir() and _regular_inside(d / "SKILL.md", sk):
                out.append((d.name, d, d / "SKILL.md"))
    cm = base / "commands"
    if cm.is_dir():
        for f in sorted(cm.rglob("*.md")):
            if _regular_inside(f, cm):
                out.append((f.relative_to(cm).with_suffix("").as_posix().replace("/", ":"), f, f))
    return out


def _hash(target: Path, cache: dict[str, list[str]]) -> str:
    key = str(target)
    sig = signature(target) if target.is_dir() else f"{target.stat().st_size}:{target.stat().st_mtime_ns}"
    hit = cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    h = hash_folder(target) if target.is_dir() else _hash_file(target)
    cache[key] = [sig, h]
    return h


def _hash_file(p: Path) -> str:
    import hashlib

    return hashlib.sha256(f"{p.name}\0{hashlib.sha256(p.read_bytes()).hexdigest()}\n".encode()).hexdigest()


def _plugins() -> list[tuple[str, str, Path]]:
    f = claude_dir() / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError):
        return []
    out = []
    for key, installs in (data.get("plugins") or {}).items():
        for inst in installs if isinstance(installs, list) else [installs]:
            p = inst.get("installPath")
            if p:
                out.append((key.split("@", 1)[0], str(inst.get("version") or ""), Path(p)))
    return out


def discover(repo_root: str | Path | None) -> list[SkillEntry]:
    cache = _load_cache()
    found: dict[str, SkillEntry] = {}
    plugins = _plugins()
    plugin_names = {p for p, _, _ in plugins}

    def add(kind: str, base: Path, prefix: str = "", origin: str | None = None) -> None:
        for name, target, md in _candidates(base):
            if kind != "plugin" and (target.is_dir() and ":" in target.name or name.split(":", 1)[0] in plugin_names and ":" in name):
                continue  # would look like another plugin's namespaced id
            try:
                fm, _ = parse(_read_md(md))
                h = _hash(target, cache)
            except OSError:
                continue
            fm_name = str(fm.get("name") or "")
            # a skill may not claim another namespace ("plugin:skill"); fall back to its folder name
            local = fm_name if fm_name and ":" not in fm_name and "/" not in fm_name else name
            sid = prefix + local
            found.setdefault(sid, SkillEntry(id=sid, name=local, kind=kind, origin=origin,
                                             path=paths.redact_home(str(target)),
                                             description=str(fm["description"]) if fm.get("description") else None,
                                             allowed_tools=str(fm["allowed-tools"]) if fm.get("allowed-tools") else None,
                                             hash=h))

    for d in _org_dirs():  # precedence: managed > personal > project
        add("org", d)
    add("user", claude_dir())
    if repo_root:
        add("project", Path(repo_root) / ".claude")
    for plugin, version, install in plugins:
        add("plugin", install, prefix=f"{plugin}:", origin=f"{plugin}@{version}")
    try:
        paths.ensure_dir(_cache_file().parent)
        _cache_file().write_text(json.dumps(cache))
    except OSError:
        pass
    return sorted(found.values(), key=lambda s: s.id)


def write_inventory(repo_root: str | Path | None, project_id: str | None) -> Path:
    """Scan and write the inventory file ingest reads."""
    out = paths.home() / "cache" / f"inventory-{project_id or 'none'}.json"
    paths.ensure_dir(out.parent)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(s) for s in discover(repo_root)]))
    os.replace(tmp, out)
    return out


if __name__ == "__main__":  # background scan launched by session-start
    import sys

    write_inventory(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None, sys.argv[2] if len(sys.argv) > 2 else None)
