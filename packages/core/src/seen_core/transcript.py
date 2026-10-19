"""Parse one turn of a Claude Code transcript (plan 9.3, findings A3/A4/A10).

The turn is the slice of the main transcript after the byte offset recorded at
prompt-submit, plus the subagent transcripts its Agent tool calls point at
(<transcript>/subagents/agent-<agentId>.jsonl). Usage is deduped by message id.
Stdlib only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_CMD = re.compile(r"<command-name>/?([\w:.-]+)</command-name>")

Usage = dict[str, dict[str, int]]


@dataclass
class SkillCall:
    name: str
    subagent: bool
    tool_use_id: str | None = None


@dataclass
class Turn:
    usage: Usage = field(default_factory=dict)
    skill_calls: list[SkillCall] = field(default_factory=list)
    slash_commands: list[str] = field(default_factory=list)
    # (source_kind, source_ref, text): prompt | file_read | tool_output | mcp | tool_input
    scan_texts: list[tuple[str, str, str]] = field(default_factory=list)
    last_text: str = ""
    version: str | None = None
    models: list[str] = field(default_factory=list)


def _lines(path: Path, offset: int, end: int | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            raw = f.read(-1 if end is None else max(0, end - offset))
    except OSError:
        return out
    for ln in raw.splitlines():
        try:
            d = json.loads(ln)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text_of(c.get("text") if isinstance(c, dict) and "text" in c else c.get("content") if isinstance(c, dict) else c)
                         for c in content)
    return "" if content is None else str(content)


_FIELDS = ("tok_in", "tok_out", "tok_cache_read", "tok_cache_write", "cw_5m", "cw_1h")


def _usage_of(u: dict[str, Any]) -> dict[str, int]:
    cc: dict[str, Any] = u["cache_creation"] if isinstance(u.get("cache_creation"), dict) else {}
    return {"tok_in": int(u.get("input_tokens") or 0), "tok_out": int(u.get("output_tokens") or 0),
            "tok_cache_read": int(u.get("cache_read_input_tokens") or 0),
            "tok_cache_write": int(u.get("cache_creation_input_tokens") or 0),
            "cw_5m": int(cc.get("ephemeral_5m_input_tokens") or 0), "cw_1h": int(cc.get("ephemeral_1h_input_tokens") or 0)}


def _add_usage(turn: Turn, msg: dict[str, Any], seen: dict[str, dict[str, int]]) -> None:
    """One message streams as several lines with the same id. Count the largest value seen per field, so a partial
    first line (output_tokens still growing) is topped up by the later lines rather than kept."""
    u = msg.get("usage")
    if not isinstance(u, dict):
        return
    model = str(msg.get("model") or "unknown")
    if model not in turn.models:
        turn.models.append(model)
    acc = turn.usage.setdefault(model, {"tok_in": 0, "tok_out": 0, "tok_cache_read": 0, "tok_cache_write": 0, "cw_5m": 0, "cw_1h": 0})
    now = _usage_of(u)
    prev = seen.setdefault(str(msg["id"]), {}) if msg.get("id") else {}
    for k in _FIELDS:
        acc[k] += max(0, now[k] - prev.get(k, 0))
        prev[k] = max(now[k], prev.get(k, 0))


def _walk(turn: Turn, lines: list[dict[str, Any]], seen: dict[str, dict[str, int]], subagent: bool,
          tool_names: dict[str, tuple[str, str]], agent_ids: list[str], since: str = "") -> None:
    for d in lines:
        if since and str(d.get("timestamp") or "~") < since:
            continue  # a resumed subagent's file holds its earlier turns too
        t = d.get("type")
        if d.get("version") and not turn.version:
            turn.version = str(d["version"])
        msg: dict[str, Any] = d["message"] if isinstance(d.get("message"), dict) else {}
        if t == "assistant":
            # one line per content block, same message id repeated: count usage once, read every block
            _add_usage(turn, msg, seen)
            for c in msg.get("content") or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "tool_use":
                    name = str(c.get("name"))
                    ti: dict[str, Any] = c["input"] if isinstance(c.get("input"), dict) else {}
                    ref = ti.get("file_path") or ti.get("url") or ""
                    tool_names[str(c.get("id"))] = (name, str(ref))
                    if name == "Skill" and ti.get("skill"):
                        turn.skill_calls.append(SkillCall(str(ti["skill"]), subagent, c.get("id")))
                    turn.scan_texts.append(("tool_input", name, json.dumps(ti)))
                elif c.get("type") == "text" and not subagent and c.get("text"):
                    turn.last_text = str(c["text"])
        elif t == "user":
            content = msg.get("content")
            if isinstance(content, str):
                m = _CMD.search(content)
                if m and not subagent:
                    turn.slash_commands.append(m.group(1))
                if not d.get("isMeta"):
                    turn.scan_texts.append(("prompt", "", content))
                continue
            for c in content or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "tool_result":
                    name, ref = tool_names.get(str(c.get("tool_use_id")), ("", ""))
                    kind = "file_read" if name == "Read" else "mcp" if name.startswith("mcp__") else "tool_output"
                    turn.scan_texts.append((kind, f"{name} {ref}".strip(), _text_of(c.get("content"))))
                    tur = d.get("toolUseResult")
                    if name in ("Agent", "Task") and isinstance(tur, dict) and tur.get("agentId"):
                        agent_ids.append(str(tur["agentId"]))
                elif c.get("type") == "text" and not d.get("isMeta") and not subagent:
                    turn.scan_texts.append(("prompt", "", str(c.get("text") or "")))


def parse_turn(transcript: str | Path, offset: int, end: int | None = None) -> Turn:
    path = Path(transcript)
    turn = Turn()
    seen: dict[str, dict[str, int]] = {}
    tools: dict[str, tuple[str, str]] = {}
    agents: list[str] = []
    main = _lines(path, offset, end)
    _walk(turn, main, seen, False, tools, agents)
    since = min((str(d["timestamp"]) for d in main if d.get("timestamp")), default="")
    subdir = path.with_suffix("") / "subagents"
    for aid in agents:
        f = subdir / f"agent-{re.sub(r'[^A-Za-z0-9_-]', '', aid)}.jsonl"
        if f.exists():
            _walk(turn, _lines(f, 0), seen, True, {}, [], since)
    return turn
