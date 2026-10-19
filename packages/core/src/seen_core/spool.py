"""Append-only per-session spool. One JSON line per hook event. Stdlib only."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from . import paths


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def untracked_marker(session_id: str) -> Any:
    return paths.snap_file(session_id).with_suffix(".untracked")


def untrack(session_id: str) -> None:
    """A session outside any git repo belongs to no project: record nothing for it (ADR 0009)."""
    f = untracked_marker(session_id)
    paths.ensure_dir(f.parent)
    f.touch()


def append(session_id: str, line: dict[str, Any]) -> None:
    if untracked_marker(session_id).exists():
        return
    f = paths.spool_file(session_id)
    paths.ensure_dir(f.parent)
    rec = {"t": now(), **line}
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, separators=(",", ":"), sort_keys=True) + "\n")


def read(session_id: str) -> list[dict[str, Any]]:
    f = paths.spool_file(session_id)
    if not f.exists():
        return []
    out = []
    for ln in f.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue  # a torn final line from a killed hook
    return out
