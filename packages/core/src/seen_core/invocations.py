"""Reconcile skill invocations from hooks, slash commands and the transcript (plan section 11)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .transcript import Turn

_SLASH = re.compile(r"^/([\w:.-]+)")


@dataclass
class Invocation:
    skill_id: str
    trigger: str  # model | user | subagent
    hash: str | None
    kind: str
    tool_use_id: str | None = None


def reconcile(spool_lines: list[dict[str, Any]], turn: Turn, prompt: str, inventory: dict[str, dict[str, Any]]) -> list[Invocation]:
    out: list[Invocation] = []

    def make(name: str, trigger: str, tuid: str | None) -> Invocation:
        s = inventory.get(name)
        return Invocation(name, trigger, s["hash"] if s else None, s["kind"] if s else "sideload", tuid)

    m = _SLASH.match(prompt.strip())
    slash = m.group(1) if m else None
    if slash and slash in inventory:  # /clear etc. are built-in commands, not skills
        out.append(make(slash, "user", None))
    seen: set[str] = set()
    for c in turn.skill_calls:
        if c.tool_use_id:
            seen.add(c.tool_use_id)
        out.append(make(c.name, "subagent" if c.subagent else "model", c.tool_use_id))
    for ln in spool_lines:  # hook-only signals: the transcript slice missed them
        if ln.get("ev") == "skill_start" and ln.get("skill") and ln.get("tool_use_id") not in seen:
            out.append(make(str(ln["skill"]), str(ln.get("trigger") or "model"), ln.get("tool_use_id")))
    return out
