"""Tiny front matter parser: `key: value`, quoted strings, [a, b] lists. Stdlib only.

Covers SKILL.md and memory files; anything fancier is treated as a plain string.
"""

from __future__ import annotations

from typing import Any


def _value(v: str) -> Any:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if v.startswith("[") and v.endswith("]"):
        return [_value(x) for x in v[1:-1].split(",") if x.strip()]
    return v


def parse(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines(keepends=True)
    fm: dict[str, Any] = {}
    for i, ln in enumerate(lines[1:], start=1):
        if ln.strip() == "---":
            return fm, "".join(lines[i + 1:])
        s = ln.split("#", 1)[0] if " #" in ln else ln
        if ":" in s and not s.startswith((" ", "\t", "-")):
            k, v = s.split(":", 1)
            fm[k.strip()] = _value(v)
    return {}, text  # unterminated block: not front matter


def dump(fm: dict[str, Any], body: str) -> str:
    out = ["---"]
    for k, v in fm.items():
        out.append(f"{k}: {'' if v is None else v}".rstrip())
    return "\n".join(out) + "\n---\n" + body
