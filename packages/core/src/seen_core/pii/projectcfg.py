"""<repo>/.seen/pii.yaml reader for hooks. Stdlib has no YAML parser, so this reads exactly the
documented schema: top-level keys with flow lists ["a", b] or block lists of strings, and
custom_rules as a block list of flat mappings. Anything else is ignored."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

MAX = 64 * 1024


def _scalar(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        inner = v[1:-1]
        return inner.replace("\\\\", "\\") if v[0] == '"' else inner
    return v


def _flow(v: str) -> list[str]:
    inner = v.strip()[1:-1]
    out, cur, q = [], "", ""
    for ch in inner:
        if q:
            cur += ch
            if ch == q:
                q = ""
        elif ch in "\"'":
            q = ch
            cur += ch
        elif ch == ",":
            out.append(_scalar(cur))
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(_scalar(cur))
    return [x for x in out if x]


def load_project(root: str | Path | None) -> dict[str, Any]:
    cfg: dict[str, Any] = {"allow_paths": [], "allow_values": [], "custom_rules": []}
    if not root:
        return cfg
    f = Path(root) / ".seen" / "pii.yaml"
    try:
        st = os.lstat(f)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX:
            return cfg
        text = f.read_text(errors="replace")
    except OSError:
        return cfg
    key = None
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        if not line.startswith((" ", "-")) and ":" in line:
            key, _, rest = line.partition(":")
            key = key.strip()
            rest = rest.strip()
            if key in cfg and rest.startswith("["):
                cfg[key] = _flow(rest)
            continue
        s = line.strip()
        if key in ("allow_paths", "allow_values") and s.startswith("- "):
            cfg[key].append(_scalar(s[2:]))
        elif key == "custom_rules":
            if s.startswith("- "):
                cfg["custom_rules"].append({})
                s = s[2:]
            if ":" in s and cfg["custom_rules"]:
                k, _, v = s.partition(":")
                cfg["custom_rules"][-1][k.strip()] = _scalar(v)
    cfg["custom_rules"] = [r for r in cfg["custom_rules"] if safe_pattern(str(r.get("pattern") or ""))]
    return cfg


# a quantified group that itself contains a quantifier or an alternation: (a+)+, (a|aa)*, (\w+\s?){2,}
_NESTED = re.compile(r"\((?:[^()\\]|\\.)*(?:[+*]|\{\d*,\d*\}|\|)(?:[^()\\]|\\.)*\)(?:[+*]|\{\d*,\d*\})")


def safe_pattern(p: str) -> bool:
    """Repo regexes run on every prompt and Python's re has no timeout: refuse catastrophic shapes."""
    if not p or len(p) > 200 or _NESTED.search(p) or re.search(r"\\[1-9]", p):
        return False
    try:
        re.compile(p)
    except re.error:
        return False
    return True
