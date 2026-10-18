"""Append-only per-session spool. One JSON line per hook event. Stdlib only."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from . import paths


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def append(session_id: str, line: dict[str, Any]) -> None:
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
