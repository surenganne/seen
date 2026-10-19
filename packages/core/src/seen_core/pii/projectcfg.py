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


def _risky(items: object, under_repeat: bool = False) -> bool:
    """Walk the parsed pattern, deny by default. A repeat with another repeat or a branch beneath it can
    backtrack exponentially; atomic groups, conditionals and backreferences are refused outright."""
    from re import _constants as C  # type: ignore[attr-defined]

    leaves = {C.LITERAL, C.NOT_LITERAL, C.ANY, C.IN, C.AT}
    for op, av in items:  # type: ignore[attr-defined]
        if op in leaves:
            continue
        if op in (C.MAX_REPEAT, C.MIN_REPEAT, C.POSSESSIVE_REPEAT):
            if under_repeat or _risky(av[2], under_repeat=True):
                return True
        elif op is C.BRANCH:
            if under_repeat or any(_risky(b, under_repeat) for b in av[1]):
                return True
        elif op is C.SUBPATTERN:
            if _risky(av[-1], under_repeat):
                return True
        elif op in (C.ASSERT, C.ASSERT_NOT):
            if _risky(av[1], under_repeat):
                return True
        else:
            return True  # ATOMIC_GROUP, GROUPREF, GROUPREF_EXISTS and anything new: unsafe until understood
    return False


def _unbounded(items: object) -> int:
    """Count unbounded repeats anywhere in the pattern. Three in a row (`.*.*.*y`) backtrack cubically under search()."""
    from re import _constants as C  # type: ignore[attr-defined]

    n = 0
    for op, av in items:  # type: ignore[attr-defined]
        if op in (C.MAX_REPEAT, C.MIN_REPEAT, C.POSSESSIVE_REPEAT):
            n += (av[1] == C.MAXREPEAT) + _unbounded(av[2])
        elif op is C.SUBPATTERN:
            n += _unbounded(av[-1])
        elif op is C.BRANCH:
            n += max((_unbounded(b) for b in av[1]), default=0)
        elif op in (C.ASSERT, C.ASSERT_NOT):
            n += _unbounded(av[1])
    return n


def safe_pattern(p: str) -> bool:
    """Repo regexes run on every prompt and Python's re has no timeout: refuse catastrophic shapes."""
    from re import _parser  # type: ignore[attr-defined]

    if not p or len(p) > 200:
        return False
    try:
        tree = _parser.parse(p)
        # ponytail: <=2 unbounded repeats still go quadratic-cubic on hostile input; detect.py's deadline is the real guard
        return not _risky(tree) and _unbounded(tree) < 3
    except (re.error, RecursionError, ValueError, TypeError):
        return False
