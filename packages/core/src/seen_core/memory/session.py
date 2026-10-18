"""Per-session memory state for the hooks: what was injected, and whether memory is loaded. Stdlib only.

state: none (project has no memory) | loaded (injected, or the model read .seen/memory) | missed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .. import config, paths


def _file(sid: str) -> Path:
    return paths.snap_file(sid).with_suffix(".mem.json")


def read(sid: str) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(_file(sid).read_text())
        return data
    except (OSError, ValueError):
        return {}


def write(sid: str, state: dict[str, Any]) -> None:
    f = _file(sid)
    paths.ensure_dir(f.parent)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, f)


def budget() -> int:
    env = os.environ.get("SEEN_MEMORY_BUDGET")
    return int(env) if env and env.isdigit() else int(config.load()["memory"]["budget_tokens"])


def inject(sid: str, root: str | None, project_id: str | None, prompt: str, changed: list[str]) -> tuple[str, dict[str, Any] | None]:
    """Returns (context text for the model, spool line) for memories not yet injected this session."""
    from .files import load
    from .rank import estimate_tokens, render, select
    from .stale import mark_stale

    st = read(sid)
    st.setdefault("ids", [])
    st.update(root=root, project_id=project_id)
    personal = paths.personal_memory_dir(project_id) if project_id else None
    valid = [m for m in load(root, personal) if m.ok]
    if not valid:
        st["state"] = "none"
        write(sid, st)
        return "", None
    if not config.load()["memory"]["inject"]:
        st["state"] = st.get("state") if st.get("state") == "loaded" else "missed"
        write(sid, st)
        return "", None
    fresh = [m for m in valid if m.id not in st["ids"]]
    picked = select(mark_stale(fresh, project_id), prompt, changed, budget()) if fresh else []
    st["state"] = "loaded"
    st["ids"] += [m.id for m in picked]
    write(sid, st)
    if not picked:
        return "", None
    return render(picked), {"ev": "memory_injected", "ids": [m.id for m in picked], "hashes": [m.content_hash for m in picked],
                            "tokens": sum(estimate_tokens(m) for m in picked)}


def mark_read(sid: str, file_path: str) -> bool:
    """The model read a file under .seen/memory: count memory as loaded (gate recovery path)."""
    st = read(sid)
    root = st.get("root")
    if not root:
        return False
    mem = os.path.realpath(os.path.join(root, ".seen", "memory")) + os.sep
    if os.path.realpath(file_path).startswith(mem):
        st["state"] = "loaded"
        write(sid, st)
        return True
    return False
