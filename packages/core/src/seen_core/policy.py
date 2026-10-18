"""Required-skill rules from <repo>/.seen/policies.yaml (plan 9.6). Evaluated at Stop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pathspec
import yaml


@dataclass(frozen=True)
class Policy:
    id: str
    title: str
    paths: list[str] = field(default_factory=list)
    require_skill: str = ""
    mode: str = "report"  # report | enforce


def load(root: str | Path | None) -> list[Policy]:
    """Invalid entries are skipped; a broken file yields no rules (doctor and the dashboard report it)."""
    if not root:
        return []
    f = Path(root) / ".seen" / "policies.yaml"
    try:
        data = yaml.safe_load(f.read_text()) if f.is_file() and not f.is_symlink() else []
    except (OSError, yaml.YAMLError):
        return []
    out = []
    for p in data if isinstance(data, list) else []:
        if not isinstance(p, dict):
            continue
        paths = p.get("paths")
        if not isinstance(p.get("id"), str) or not isinstance(paths, list) or not all(isinstance(x, str) for x in paths) \
                or not isinstance(p.get("require_skill"), str):
            continue
        mode = p.get("mode") if p.get("mode") in ("report", "enforce") else "report"
        out.append(Policy(id=p["id"], title=str(p.get("title") or p["id"]), paths=paths, require_skill=p["require_skill"], mode=mode))
    return out


def matches(p: Policy, files: list[str]) -> list[str]:
    spec = pathspec.PathSpec.from_lines("gitignore", p.paths)
    return [f for f in files if spec.match_file(f)]


def evaluate(policies: list[Policy], files: list[str], skills_run: set[str]) -> list[tuple[str, bool]]:
    """For each policy whose paths match a touched file: met = the required skill ran this turn."""
    return [(p.id, p.require_skill in skills_run) for p in policies if matches(p, files)]


def block_reason(p: Policy, files: list[str]) -> str:
    hit = matches(p, files)
    shown = ", ".join(hit[:3]) + (f" and {len(hit) - 3} more" if len(hit) > 3 else "")
    return f"Run {p.require_skill} before finishing, because this change touches {shown}."
