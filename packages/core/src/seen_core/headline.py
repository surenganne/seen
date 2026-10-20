"""One-line descriptions of a change, shared by the Timeline, the CLI and the report."""

from __future__ import annotations

import re
from collections import Counter

_TAG = re.compile(r"<(command-name|command-args|summary)>(.*?)</\1>", re.S)


def request_line(prompt: str | None) -> str | None:
    """The request on one line. Text Claude Code injects reads as what it is, not as raw tags."""
    if not prompt:
        return None
    tags = {k: " ".join(v.split()) for k, v in _TAG.findall(prompt)}
    if prompt.lstrip().startswith("<task-notification>"):
        return "Automatic follow-up: a background task finished" + (f" ({tags['summary'][:300]})" if tags.get("summary") else "")
    if tags.get("command-name"):
        return " ".join(x for x in (tags["command-name"], tags.get("command-args", "")) if x)[:400]
    return " ".join(prompt.split())[:400]


def areas_of(paths: list[str]) -> list[str]:
    """Top folders a change touched: two levels deep, a root file as (root). Most files first, ties in first-seen order."""
    def area(p: str) -> str:
        parts = p.strip("/").split("/")
        return "(root)" if len(parts) == 1 else parts[0] if len(parts) == 2 else "/".join(parts[:2])
    return [a for a, _ in Counter(area(p) for p in paths).most_common(3)]


_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def clean(text: str | None) -> str:
    """Printable text only: whitespace runs become one space, other control characters (ANSI/OSC escapes) are dropped."""
    return _CTRL.sub("", " ".join((text or "").split()))


_SENTENCE = re.compile(r"(?<=[.!?])\s")


def headline_of(summary: str | None, request: str | None, files: list[str]) -> str:
    """One line for a change: the first sentence of the reply, else the request, else what was touched."""
    for src in (summary, request):
        text = clean((src or "").replace("*", "").replace("`", ""))
        text = _SENTENCE.split(text, 1)[0] if text else ""
        if len(text) >= 15:
            return text if len(text) <= 140 else text[:139].rstrip() + "…"
    n = len(files)
    return f"Changed {n} {'file' if n == 1 else 'files'} in {', '.join(areas_of(files))}"
