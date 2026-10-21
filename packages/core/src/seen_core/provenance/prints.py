"""Line fingerprints for provenance (spec sections 4 and 5): keyed hashes of the lines an agent added. Stdlib only.
Never returns or logs line text, only hex fingerprints and counts."""

from __future__ import annotations

import hashlib
import hmac
import os
from collections import Counter
from typing import Any

MAX_LINES = 5_000  # candidate lines per tool call
MAX_BYTES = 1_000_000  # added text per tool call
_MIN_ALNUM = 10  # fewer alphanumerics than this is a trivial line
_ENC = "surrogatepass"  # a lone surrogate (json.loads accepts one) must not raise
_TAG = b"seen-line-v1\0"  # lets a later version change the scheme


def normalize(line: str) -> str:
    return " ".join(line.split())


def is_trivial(line: str) -> bool:
    return sum(c.isalnum() for c in normalize(line)) < _MIN_ALNUM


def fingerprint(line: str, key: bytes) -> bytes:
    return hmac.new(key, _TAG + normalize(line).encode(errors=_ENC), hashlib.sha256).digest()[:8]


def split_lines(text: str) -> list[str]:
    """Split on \\n only, as blame and diff do (splitlines() also splits on FF, VT, NEL, U+2028); `normalize` drops a CR."""
    out = text.split("\n")
    if out[-1] == "":
        out.pop()
    return out


def added_lines(tool_name: str, tool_input: dict[str, Any]) -> list[str] | None:
    """Raw lines the tool added, or None when it is not a text-writing tool we fingerprint."""
    if not isinstance(tool_input, dict):
        return None
    if tool_name == "Write":
        text = tool_input.get("content")
    elif tool_name == "Edit":
        new, old = tool_input.get("new_string"), tool_input.get("old_string")
        if not isinstance(new, str) or not isinstance(old, str):
            return None
        # multiset difference on normalised lines: a line kept from old_string is not an addition
        left = Counter(normalize(s) for s in split_lines(old))
        out = []
        for s in split_lines(new):
            n = normalize(s)
            if left[n] > 0:
                left[n] -= 1
            else:
                out.append(s)
        return out
    elif tool_name == "NotebookEdit":
        text = "" if tool_input.get("edit_mode") == "delete" else tool_input.get("new_source")
    else:
        return None
    return split_lines(text) if isinstance(text, str) else None


def _rel(path: str, root: str) -> str | None:
    try:
        rel = os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    except (ValueError, OSError):  # NUL in the path, unresolvable path
        return None
    return None if rel in (".", "..") or rel.startswith(".." + os.sep) or os.path.isabs(rel) else rel


def capture(tool_name: str, tool_input: dict[str, Any], root: str | None, key: bytes) -> dict[str, Any] | None:
    """{"path", "fps" (16-char hex), "n" (candidate lines), "capped"} or None when there is nothing to record."""
    lines = added_lines(tool_name, tool_input)
    if not lines or root is None:
        return None
    path = tool_input.get("notebook_path" if tool_name == "NotebookEdit" else "file_path")
    if not isinstance(path, str):
        return None
    rel = _rel(path, root)
    if rel is None or "\0" in "\n".join(lines)[:8000]:  # outside the repo, or binary
        return None
    cands = [s for s in lines if not is_trivial(s)]
    if not cands:
        return None
    capped = len(cands) > MAX_LINES or sum(len(s.encode(errors=_ENC)) for s in lines) > MAX_BYTES
    fps = [] if capped else [fingerprint(s, key).hex() for s in cands]
    return {"path": rel, "fps": fps, "n": len(cands), "capped": capped}
