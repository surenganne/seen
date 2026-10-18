"""seen-hook: the Claude Code hook entry point.

Hot path is stdlib only and appends spool lines. Hooks fail open: any exception
exits 0 and logs. Only the memory gate, the blocked-skill check, PII block mode and
policy enforcement return 2, and always explicitly, never through an exception.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import traceback
from dataclasses import dataclass
from typing import Any

from . import paths, spool

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


@dataclass
class Result:
    code: int = 0
    stdout: str = ""
    stderr: str = ""


def _log_exception(event: str) -> None:
    try:
        f = paths.hook_log()
        paths.ensure_dir(f.parent)
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(f"{spool.now()} {event}\n{traceback.format_exc()}\n")
    except OSError:
        pass


def _base(p: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"prompt_id": p.get("prompt_id")}
    if p.get("agent_id"):
        out["agent_id"] = p["agent_id"]
    return out


def _target_path(ti: dict[str, Any]) -> str | None:
    p = ti.get("file_path") or ti.get("notebook_path") or ti.get("path")
    return paths.redact_home(p) if isinstance(p, str) else None


def _cmd0(command: str) -> str | None:
    try:
        toks = shlex.split(command)
    except ValueError:
        toks = command.split()
    for t in toks:
        if "=" not in t:  # skip VAR=value prefixes, they can carry secrets
            return os.path.basename(t)
    return None


def _write_json(f: Any, obj: Any) -> None:
    paths.ensure_dir(f.parent)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj))
    os.replace(tmp, f)


def _file_hash(f: Any) -> str | None:
    import hashlib

    try:
        return hashlib.sha256(f.read_bytes()).hexdigest()
    except OSError:
        return None


def _on_session_start(p: dict[str, Any]) -> Result:
    from pathlib import Path

    from . import brand
    from .project import resolve_project

    proj = resolve_project(p.get("cwd") or ".")
    seen_dir = Path(proj.root) / ".seen" if proj else None
    spool.append(p["session_id"], {
        "ev": "session_start", "source": p.get("source"), "cwd": paths.redact_home(p.get("cwd") or ""),
        "plugin_version": brand.VERSION, "config_hash": _file_hash(paths.config_toml()),
        "lock_hash": _file_hash(seen_dir / "skills.lock.json") if seen_dir else None,
        "policies_hash": _file_hash(seen_dir / "policies.yaml") if seen_dir else None,
        "transcript_path": p.get("transcript_path"),
        "project_id": proj.id if proj else None, "project_name": proj.name if proj else None,
        "remote": proj.remote if proj else None, "root": proj.root if proj else None,
    })
    _scan_inventory(proj.root if proj else None, proj.id if proj else None)
    return Result()


def _scan_inventory(root: str | None, project_id: str | None) -> None:
    """Skill hashing takes 0.2-1s on a big install: run it detached, never on the hot path."""
    if os.environ.get("SEEN_INVENTORY_SYNC"):
        from .skills.scan import write_inventory

        write_inventory(root, project_id)
        return
    import subprocess

    cwd = paths.ensure_dir(paths.home())
    # -I and a trusted cwd: the repo the agent works in must not shadow our modules
    subprocess.Popen([sys.executable, "-I", "-m", "seen_core.skills.scan", root or "", project_id or "none"],
                     cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def _on_prompt_submit(p: dict[str, Any]) -> Result:
    from .gitdelta import snapshot

    tp = p.get("transcript_path")
    offset = os.path.getsize(tp) if tp and os.path.exists(tp) else 0
    cwd = p.get("cwd") or "."
    before = snapshot(cwd)
    _write_json(paths.snap_file(p["session_id"]), {"prompt_id": p.get("prompt_id"), "cwd": cwd, "before": before})
    import hashlib
    import re

    from . import config

    prompt = p.get("prompt") or ""
    m = re.match(r"^/([\w:.-]+)", prompt.strip())
    line: dict[str, Any] = {"ev": "turn_start", **_base(p), "transcript_offset": offset, "cwd": cwd, "head": before["head"],
                            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "prompt_len": len(prompt),
                            "slash": m.group(1) if m else None}
    if config.load()["pii"]["store_prompt_text"] == "full":
        line["prompt"] = prompt  # only on explicit opt-in; redacted storage arrives with redact.py
    spool.append(p["session_id"], line)
    return Result()


def _on_pre_edit(p: dict[str, Any]) -> Result:
    return Result()


def _on_pre_read(p: dict[str, Any]) -> Result:
    return Result()


def _on_pre_skill(p: dict[str, Any]) -> Result:
    ti = p.get("tool_input") or {}
    spool.append(p["session_id"], {"ev": "skill_start", **_base(p), "skill": ti.get("skill"),
                                   "tool_use_id": p.get("tool_use_id"),
                                   "trigger": "subagent" if p.get("agent_id") else "model"})
    return Result()


def _on_post_tool(p: dict[str, Any]) -> Result:
    ti = p.get("tool_input") or {}
    tool = p.get("tool_name")
    line: dict[str, Any] = {"ev": "tool", **_base(p), "tool": tool, "tool_use_id": p.get("tool_use_id")}
    if (path := _target_path(ti)) is not None:
        line["path"] = path
    if tool == "Skill":
        line["skill"] = ti.get("skill")
    if tool == "Bash" and isinstance(ti.get("command"), str):
        line["cmd0"] = _cmd0(ti["command"])
    spool.append(p["session_id"], line)
    return Result()


def _on_stop(p: dict[str, Any]) -> Result:
    spool.append(p["session_id"], {"ev": "turn_end", **_base(p), "stop_hook_active": bool(p.get("stop_hook_active")),
                                   "last_message": (p.get("last_assistant_message") or "")[:2000]})
    from . import ingest  # heavy imports only here, once per turn

    ingest.finish_turn(p["session_id"])
    return Result()


def _on_session_end(p: dict[str, Any]) -> Result:
    spool.append(p["session_id"], {"ev": "session_end", **_base(p), "reason": p.get("reason")})
    from . import ingest

    ingest.finish_session(p["session_id"])
    return Result()


def run(event: str, raw: bytes) -> Result:
    sid = None
    try:
        p = json.loads(raw or b"{}")
        sid = p.get("session_id") or "unknown"
        p["session_id"] = sid
        handler = globals().get("_on_" + event.replace("-", "_"))
        if handler is None:
            return Result()
        r: Result = handler(p)
        return r
    except Exception as e:  # fail open
        _log_exception(event)
        if sid:
            try:
                spool.append(sid, {"ev": "capture_gap", "hook": event, "error": type(e).__name__})
            except Exception:
                pass
        return Result()


def main() -> None:
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    r = run(event, sys.stdin.buffer.read())
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    sys.exit(r.code)


if __name__ == "__main__":
    main()
