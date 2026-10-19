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
        et, _ev, tb = sys.exc_info()
        # frames and the exception type only: the message can echo a prompt value, and frames carry home paths
        body = paths.redact_home("".join(traceback.format_tb(tb))).replace(os.path.expanduser("~"), "~")
        with os.fdopen(os.open(f, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600), "a", encoding="utf-8") as fh:
            fh.write(f"{spool.now()} {event}\n{body}{et.__name__ if et else 'Error'}\n\n")
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


def _file_hash(f: Any, cap: int = 1024 * 1024) -> str | None:
    """sha256 of a small regular file. Repo files are untrusted: no symlinks, fifos or giants."""
    import hashlib
    import stat

    try:
        st = os.lstat(f)
        if not stat.S_ISREG(st.st_mode) or st.st_size > cap:
            return None
        fd = os.open(f, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(cap + 1)
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest() if len(data) <= cap else None


def _on_session_start(p: dict[str, Any]) -> Result:
    from pathlib import Path

    from . import brand
    from .project import resolve_project

    proj = resolve_project(p.get("cwd") or ".")
    if proj is None:
        spool.untrack(p["session_id"])
        return Result()
    root = (proj.worktree or proj.root) if proj else None  # a worktree has its own .seen/* and files
    seen_dir = Path(root) / ".seen" if root else None
    spool.append(p["session_id"], {
        "ev": "session_start", "source": p.get("source"), "cwd": paths.redact_home(p.get("cwd") or ""),
        "plugin_version": brand.VERSION, "entrypoint": os.environ.get("CLAUDE_CODE_ENTRYPOINT"), "config_hash": _file_hash(paths.config_toml()),
        "lock_hash": _file_hash(seen_dir / "skills.lock.json") if seen_dir else None,
        "policies_hash": _file_hash(seen_dir / "policies.yaml") if seen_dir else None,
        "transcript_path": p.get("transcript_path"),
        "project_id": proj.id if proj else None, "project_name": proj.name if proj else None,
        "remote": proj.remote if proj else None, "root": root, "project_root": proj.root if proj else None,
    })
    _scan_inventory(root, proj.id if proj else None)
    from .memory import session as msess

    text, line = msess.inject(p["session_id"], root, proj.id if proj else None, "", [])
    if line:
        spool.append(p["session_id"], {**line, **_base(p)})
    return _context("SessionStart", text)


def _context(event: str, text: str, system_message: str | None = None) -> Result:
    """Context for the model uses the JSON form confirmed in Phase 0 (A5); systemMessage reaches the user only (A11)."""
    out: dict[str, Any] = {}
    if text:
        out["hookSpecificOutput"] = {"hookEventName": event, "additionalContext": text}
    if system_message:
        out["systemMessage"] = system_message
    return Result(stdout=json.dumps(out) if out else "")


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
    import re

    from . import config, secret

    prompt = p.get("prompt") or ""
    m = re.match(r"^/([\w:.-]+)", prompt.strip())
    line: dict[str, Any] = {"ev": "turn_start", **_base(p), "transcript_offset": offset, "cwd": cwd, "head": before["head"],
                            "prompt_hmac": secret.keyed(prompt, 64), "prompt_len": len(prompt),
                            "slash": m.group(1) if m else None}
    from .memory import session as msess

    cfg = config.load()["pii"]
    st = msess.read(p["session_id"])
    from .pii.projectcfg import load_project

    pcfg = load_project(st.get("root"))
    warn = None
    found: list[Any] = []
    shown: list[Any] = []
    allowlisted, blocked = 0, False
    if cfg["mode"] != "off":
        from .pii.detect import scan_with_stats

        found, allowlisted = scan_with_stats(prompt, only=cfg["types"] + ["custom"], allow_values=pcfg["allow_values"],
                                             custom_rules=pcfg["custom_rules"], min_confidence="low")
        shown = [f for f in found if f.confidence in _at_least(cfg["min_confidence"])]
        blocked = cfg["mode"] == "block" and bool(shown)
    store = cfg["store_prompt_text"]
    if blocked:
        pass  # a blocked prompt never reaches the model and is never stored: only its keyed hash and length remain
    elif store == "full":
        line["prompt"] = prompt
    elif store == "redacted":
        from .redact import redact

        line["prompt"] = redact(prompt, allow_values=pcfg["allow_values"], custom_rules=pcfg["custom_rules"])
    spool.append(p["session_id"], line)
    if found or allowlisted:
        spool.append(p["session_id"], {"ev": "pii_prompt", **_base(p), "blocked": bool(blocked), "allowlisted": allowlisted,
                                       "findings": [{"type": f.type, "confidence": f.confidence, "count": f.count,
                                                     "distinct": f.distinct, "detector": f.detector, "fingerprints": f.fingerprints}
                                                    for f in found]})
    what = ", ".join(sorted({f"{f.type} x{f.count}" for f in shown}))
    if blocked:
        return Result(code=2, stderr=f"Seen blocked this prompt: it contains {what}. Remove the personal data or secrets "
                                     "and send it again (PII mode is 'block'; values were not stored).")
    if shown and cfg["mode"] == "warn":
        warn = f"Seen: this prompt contains {what}. It will go to the model provider. (Values were not stored.)"
    changed = list(before["numstat"]) + list(before["untracked"])
    text, mline = msess.inject(p["session_id"], st.get("root"), st.get("project_id"), prompt, changed)
    if mline:
        spool.append(p["session_id"], {**mline, **_base(p)})
    return _context("UserPromptSubmit", text, warn)


def _at_least(level: str) -> set[str]:
    order = ["low", "medium", "high"]
    return set(order[order.index(level):]) if level in order else {"medium", "high"}


GATE_MSG = ("Seen: project memory did not load for this session, so edits are paused. Read the files in "
            "{folder} first (they hold this project's decisions, conventions and gotchas), then retry the edit.")


def _on_pre_edit(p: dict[str, Any]) -> Result:
    from . import config
    from .memory import session as msess

    ti = p.get("tool_input") or {}
    target = str(ti.get("file_path") or ti.get("notebook_path") or "")
    st = msess.read(p["session_id"])
    root = st.get("root")
    mem_dir = os.path.join(root, ".seen", "memory") if root else None
    decision, reason = "allow", "loaded"
    if mem_dir and os.path.realpath(target).startswith(os.path.realpath(mem_dir) + os.sep):
        reason = "memory_folder"  # saving memory is always allowed
    elif not config.load()["memory"]["gate"]:
        reason = "gate_off"
    elif st.get("state") == "missed":
        decision, reason = "block", "memory_not_loaded"
    elif st.get("state") in (None, "none"):
        reason = "no_memory"
    spool.append(p["session_id"], {"ev": "gate", **_base(p), "hook": "pre-edit", "decision": decision, "reason": reason})
    if decision == "block":
        return Result(code=2, stderr=GATE_MSG.format(folder=paths.redact_home(str(mem_dir))))
    return Result()


PRE_READ_CAP = 256 * 1024
PRE_READ_CHUNK = 16 * 1024


def _on_pre_read(p: dict[str, Any]) -> Result:
    from . import config
    from .memory import session as msess

    target = str((p.get("tool_input") or {}).get("file_path") or "")
    if not target:
        return Result()
    msess.mark_read(p["session_id"], target)
    cfg = config.load()["pii"]
    if cfg["mode"] != "block":
        return Result()  # report/warn: the Stop-time scan records what the read exposed
    return _pre_read_scan(p, target, cfg, msess.read(p["session_id"]).get("root"))


def _pre_read_scan(p: dict[str, Any], target: str, cfg: dict[str, Any], root: str | None) -> Result:
    import time

    from .pii.detect import scan_with_stats
    from .pii.projectcfg import load_project
    from .pii.stopscan import _rel, path_allowed

    pcfg = load_project(root)
    rel = _rel(target, root)
    if path_allowed(rel, pcfg["allow_paths"]):
        return Result()
    try:
        size = os.path.getsize(target)
        with open(target, "rb") as fh:
            data = fh.read(PRE_READ_CAP).decode("utf-8", errors="replace")
    except OSError:
        return Result()
    budget = float(os.environ.get("SEEN_PRE_READ_BUDGET_MS") or 100) / 1000
    start = time.perf_counter()
    hits = []
    for i in range(0, len(data), PRE_READ_CHUNK):
        if time.perf_counter() - start > budget:
            return _defer(p, rel, "time")
        chunk = data[max(0, i - 64): i + PRE_READ_CHUNK]  # overlap so a value split across chunks is still seen
        found, _ = scan_with_stats(chunk, only=list(cfg["types"]) + ["custom"], allow_values=pcfg["allow_values"],
                                   custom_rules=pcfg["custom_rules"], min_confidence="high")
        hits += found
        if hits:
            break
    if not hits:
        return _defer(p, rel, "size") if size > PRE_READ_CAP else Result()
    what = ", ".join(sorted({f.type for f in hits}))
    spool.append(p["session_id"], {"ev": "gate", **_base(p), "hook": "pre-read", "decision": "block", "reason": "pii",
                                   "path": rel, "types": sorted({f.type for f in hits})})
    return Result(code=2, stderr=f"Seen blocked reading {rel}: it contains high-confidence {what} (PII mode is 'block'). "
                                 "Use a redacted or synthetic copy, or ask the user to allowlist the path in .seen/pii.yaml.")


def _defer(p: dict[str, Any], rel: str, reason: str) -> Result:
    spool.append(p["session_id"], {"ev": "pre_read_deferred", **_base(p), "path": rel, "reason": reason})
    why = "is over 256 KB" if reason == "size" else "took longer than the 100 ms scan budget"
    return _context("PreToolUse", "", f"Seen: {rel} {why}, so it was not scanned before the read. "
                                       "It will be scanned after this turn (detect only).")


def _on_pre_skill(p: dict[str, Any]) -> Result:
    from .memory import session as msess
    from .skills import lock

    ti = p.get("tool_input") or {}
    skill = str(ti.get("skill") or "")
    root = msess.read(p["session_id"]).get("root")
    if root and lock.is_blocked(lock.load(root), skill):  # check first: a blocked attempt is not a skill run
        spool.append(p["session_id"], {"ev": "gate", **_base(p), "hook": "pre-skill", "decision": "block", "reason": "skill_blocked"})
        return Result(code=2, stderr=f"Seen: the skill {skill.strip()[:80]} is blocked for this project (.seen/skills.lock.json). "
                                     "Continue without it, or ask the user to unblock it.")
    spool.append(p["session_id"], {"ev": "skill_start", **_base(p), "skill": skill,
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
    from .redact import redact, summarise

    last = p.get("last_assistant_message") or ""
    # never the raw reply: it routinely echoes what the user typed
    spool.append(p["session_id"], {"ev": "turn_end", **_base(p), "stop_hook_active": bool(p.get("stop_hook_active")),
                                   "summary": redact(summarise(last)) if last else ""})
    from . import ingest  # heavy imports only here, once per turn

    r = ingest.finish_turn(p["session_id"])
    # enforce mode: block Stop once per turn; stop_hook_active means we already asked (A2), so never loop
    if r.get("block_reason") and not p.get("stop_hook_active"):
        spool.append(p["session_id"], {"ev": "gate", **_base(p), "hook": "stop", "decision": "block", "reason": "policy_missed"})
        return Result(stdout=json.dumps({"decision": "block", "reason": r["block_reason"]}))
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
