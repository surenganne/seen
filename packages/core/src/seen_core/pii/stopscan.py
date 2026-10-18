"""Stop-time PII scan (plan 11B): what reached the model this turn, what tools sent out, what landed in the repo.

Detect and report only: by Stop the data has already gone. Sources are recorded as tool name and
repo-relative path, never command arguments; values never leave this function except as fingerprints.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pathspec

from .. import gitutil, paths
from ..transcript import Turn
from .detect import Finding, scan_with_stats

NETWORK_TOOLS = {"WebFetch", "WebSearch"}
NETWORK_CMDS = {"curl", "wget", "http", "https", "nc", "ncat", "ssh", "scp", "sftp", "rsync", "aws", "gcloud", "az", "gh", "ftp"}
MAX_FILE = 1024 * 1024


@dataclass
class Row:
    type: str
    confidence: str
    source_kind: str
    source_ref: str
    destination: str
    detector: str
    count: int = 0
    fingerprints: list[str] = field(default_factory=list)

    @property
    def distinct(self) -> int:
        return len(self.fingerprints)


def _rel(path: str, root: str | None) -> str:
    if root and os.path.isabs(path):
        try:
            rp = os.path.relpath(os.path.realpath(path), os.path.realpath(root))
            if not rp.startswith(".."):
                return rp
        except ValueError:
            pass
    return paths.redact_home(path)


class Collector:
    def __init__(self, cfg: dict[str, Any], pcfg: dict[str, Any]) -> None:
        self.cfg, self.pcfg = cfg, pcfg
        self.rows: dict[tuple[str, str, str, str, str], Row] = {}
        self.allowlisted = 0
        self.allow_paths = pathspec.PathSpec.from_lines("gitignore", pcfg.get("allow_paths") or [])

    def path_allowed(self, rel: str) -> bool:
        return bool(rel) and self.allow_paths.match_file(rel)

    def add(self, text: str, kind: str, ref: str, dest: str) -> None:
        if not text:
            return
        found, allowed = scan_with_stats(text, only=list(self.cfg["types"]) + ["custom"], allow_values=self.pcfg.get("allow_values"),
                                         custom_rules=self.pcfg.get("custom_rules"), min_confidence="low")
        self.allowlisted += allowed
        for f in found:
            self._merge(f, kind, ref, dest)

    def _merge(self, f: Finding, kind: str, ref: str, dest: str) -> None:
        key = (f.type, f.confidence, kind, ref, dest)
        r = self.rows.setdefault(key, Row(f.type, f.confidence, kind, ref, dest, f.detector))
        r.count += f.count
        for fp in f.fingerprints:
            if fp not in r.fingerprints:
                r.fingerprints.append(fp)


def _cmd0(tool_input_json: str) -> str:
    import json
    import shlex

    try:
        cmd = str(json.loads(tool_input_json).get("command") or "")
        toks = [t for t in shlex.split(cmd) if "=" not in t]
    except (ValueError, AttributeError):
        return ""
    return os.path.basename(toks[0]) if toks else ""


def scan_transcript(c: Collector, turn: Turn, root: str | None) -> None:
    if not c.cfg.get("scan_tool_results", True):
        return
    for kind, ref, text in turn.scan_texts:
        tool, _, target = ref.partition(" ")
        if kind == "prompt":
            continue  # scanned (and possibly blocked) at prompt-submit
        if kind == "file_read":
            rel = _rel(target, root)
            if c.path_allowed(rel):
                c.allowlisted += 1
                continue
            c.add(text, "file_read", f"Read {rel}", "model")
        elif kind == "mcp":
            parts = tool.split("__")
            c.add(text, "mcp", "MCP " + ".".join(parts[1:]) if len(parts) > 2 else "MCP " + tool, "model")
        elif kind == "tool_output":
            c.add(text, "tool_output", f"{tool or 'Tool'} output", "model")
        elif kind == "tool_input":
            if tool in NETWORK_TOOLS or tool.startswith("mcp__"):
                name = "MCP " + ".".join(tool.split("__")[1:]) if tool.startswith("mcp__") else tool
                c.add(text, "tool_input", name, "network")
            elif tool == "Bash" and _cmd0(text) in NETWORK_CMDS:
                c.add(text, "tool_input", "Bash network command", "network")


def scan_memory(c: Collector, root: str | None, project_id: str | None, ids: list[str]) -> None:
    if not ids:
        return
    from ..memory.files import load

    personal = paths.personal_memory_dir(project_id) if project_id else None
    for m in load(root, personal):
        if m.ok and m.id in ids:
            c.add(m.body, "injected_memory", f"Memory {m.id}", "model")


def _read_capped(p: Path) -> str:
    try:
        st = os.lstat(p)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE:
            return ""
        with open(p, "rb") as f:
            data = f.read(MAX_FILE)
    except OSError:
        return ""
    return "" if b"\0" in data[:8000] else data.decode("utf-8", errors="replace")


def scan_diff(c: Collector, root: str | None, files: list[str], before_head: str | None, untracked: set[str]) -> None:
    if not root or not files or not c.cfg.get("scan_diff", True):
        return
    tracked = [f for f in files if f not in untracked and not c.path_allowed(f)]
    if tracked and before_head:
        out = gitutil.run(root, "diff", "--unified=0", "--no-color", "--no-renames", "--end-of-options", before_head, "--", *tracked) or ""
        current = None
        added: dict[str, list[str]] = {}
        for ln in out.splitlines():
            if ln.startswith("+++ "):
                current = ln[6:] if ln.startswith("+++ b/") else None
            elif ln.startswith("+") and current:
                added.setdefault(current, []).append(ln[1:])
        for path, lines in added.items():
            c.add("\n".join(lines), "diff_added", path, "repo")
    for f in sorted(untracked & set(files)):
        if not c.path_allowed(f):
            c.add(_read_capped(Path(root) / f), "diff_added", f, "repo")


