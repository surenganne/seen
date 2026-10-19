"""Span redaction (plan 11B): detected values become [TYPE] markers; home paths become ~. Stdlib only."""

from __future__ import annotations

import os
import re
from typing import Any

from .pii.detect import scan


def redact(text: str, *, allow_values: list[str] | None = None, custom_rules: list[dict[str, Any]] | None = None) -> str:
    spans: list[tuple[int, int, str]] = []
    for f in scan(text, allow_values=allow_values, custom_rules=custom_rules):
        spans += [(s, e, f.type.upper()) for s, e in f.spans]
    out, last = [], 0
    for s, e, label in sorted(spans):
        if s < last:
            continue
        out.append(text[last:s] + f"[{label}]")
        last = e
    out.append(text[last:])
    red = "".join(out)
    home = os.path.expanduser("~")
    return red.replace(home + "/", "~/").replace(home, "~") if home and home != "/" else red


def summarise(text: str) -> str:
    """First sentence of the assistant's final message, trimmed to 120 characters (plan 9.4)."""
    first = re.split(r"(?<=[.!?])\s|\n", text.strip(), maxsplit=1)[0].strip()
    return first[:120]
