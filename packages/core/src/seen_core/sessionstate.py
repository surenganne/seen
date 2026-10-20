"""Per-session state for the hooks (repo root and project id, set at session start). Stdlib only."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from . import paths


def _file(sid: str) -> Path:
    return paths.snap_file(sid).with_suffix(".state.json")


def read(sid: str) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(_file(sid).read_text())
        return data
    except (OSError, ValueError):
        return {}


def write(sid: str, state: dict[str, Any]) -> None:
    f = _file(sid)
    paths.ensure_dir(f.parent)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=f".{f.name}.", suffix=".tmp")  # unique per writer: parallel hooks share a session
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(state))
    os.replace(tmp, f)
