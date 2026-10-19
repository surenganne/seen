"""seen import: record past Claude Code sessions from their transcripts (ADR 0007).

Transcripts live in <claude config>/projects/<cwd with non-alphanumerics as '-'>/<session_id>.jsonl. Each user
prompt starts a turn; the turn's slice goes through the same parser, pricing, redaction, PII scan, skill and policy
code as live capture. What a transcript cannot tell us stays empty instead of guessed: no git status or HEADs, no
memory state; line counts come from the Edit/Write inputs. Sessions already in the ledger are skipped, so re-running
is safe and never touches live-recorded sessions. A transcript still being written stays open (no end) and a later
run adds its new turns.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import audit, ingest, policy, pricing, spool
from .db import ledger_session
from .db.models import Change, ChangeFile, Project, Session
from .hook import EDIT_TOOLS
from .invocations import reconcile
from .pii import stopscan
from .pii.detect import scan_with_stats
from .pii.projectcfg import load_project
from .project import resolve_project
from .redact import redact, summarise
from .skills import lock
from .transcript import parse_turn


@dataclass
class Result:
    sessions: int = 0
    changes: int = 0
    skipped: int = 0
    cost_usd: float = 0.0


QUIET = timedelta(minutes=30)  # same window the Sessions page uses for "active"


def encode_dir(path: str | Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def transcript_dirs(root: str, worktree: str) -> list[Path]:
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
    return [d for d in dict.fromkeys(base / encode_dir(p) for p in (root, worktree)) if d.is_dir()]


def _prompt_of(d: dict[str, Any]) -> str | None:
    """The text of a real user prompt line, or None for tool results, meta lines and compaction summaries."""
    if d.get("type") != "user" or d.get("isMeta") or d.get("isCompactSummary") or d.get("isSidechain"):
        return None
    c = (d.get("message") or {}).get("content")
    if isinstance(c, str):
        return None if c.startswith(("<local-command-stdout>", "<local-command-caveat>")) else c
    if isinstance(c, list) and not any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
        texts = [str(x.get("text") or "") for x in c if isinstance(x, dict) and x.get("type") == "text"]
        return "\n".join(texts) if texts else None
    return None


def _read(path: Path) -> list[tuple[int, dict[str, Any]]]:
    out, off = [], 0
    with open(path, "rb") as f:
        for raw in f:
            try:
                d = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                d = None
            if isinstance(d, dict):
                out.append((off, d))
            off += len(raw)
    return out


def _nlines(v: Any) -> int:
    s: str = v if isinstance(v, str) else ""
    return s.count("\n") + (1 if s and not s.endswith("\n") else 0)


def _rel(p: str, root: str) -> str | None:
    full = os.path.realpath(p if os.path.isabs(p) else os.path.join(root, p))
    return os.path.relpath(full, root) if full == root or full.startswith(root + os.sep) else None


def _tools(lines: list[dict[str, Any]], root: str) -> tuple[list[tuple[str, str, str | None]], dict[str, list[int]]]:
    """(timestamp, tool name, repo-relative path) per tool call, and {path: [added, removed]} from edit inputs."""
    calls: list[tuple[str, str, str | None]] = []
    files: dict[str, list[int]] = {}
    for d in lines:
        if d.get("type") != "assistant":
            continue
        for c in (d.get("message") or {}).get("content") or []:
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            name = str(c.get("name"))
            ti: dict[str, Any] = c["input"] if isinstance(c.get("input"), dict) else {}
            fp = ti.get("file_path") or ti.get("notebook_path")
            rel = _rel(str(fp), root) if fp else None
            calls.append((str(d.get("timestamp") or ""), name, rel))
            if name in EDIT_TOOLS and rel:
                edits: list[Any] = ti["edits"] if name == "MultiEdit" and isinstance(ti.get("edits"), list) else [ti]
                acc = files.setdefault(rel, [0, 0])
                for e in edits:
                    e = e if isinstance(e, dict) else {}
                    acc[0] += _nlines(e.get("new_string") if "new_string" in e else e.get("content") or e.get("new_source"))
                    acc[1] += _nlines(e.get("old_string"))
    return calls, files


def import_project(cwd: str | Path, dry_run: bool = False) -> Result:
    from . import config

    proj = resolve_project(cwd)
    if proj is None:
        raise ValueError("not inside a git repository")
    res = Result()
    files_ = sorted({f for d in transcript_dirs(proj.root, proj.worktree) for f in d.glob("*.jsonl")})
    with ledger_session() as db:
        known = dict(db.query(Session.id, Session.source).all())
        no_ep = {sid for (sid,) in db.query(Session.id).filter(Session.entrypoint.is_(None))}
    cfg = config.load()["pii"]
    pcfg = load_project(proj.root)
    for tp in files_:
        sid = tp.stem
        if sid in no_ep and not dry_run and (ep := _entrypoint(tp)):
            with ledger_session() as db:
                if (row := db.get(Session, sid)) is not None:
                    row.entrypoint = ep
                    db.commit()
        if sid in known and known[sid] != "imported":
            res.skipped += 1
            continue
        lines = _read(tp)
        starts = [i for i, (_, d) in enumerate(lines) if _prompt_of(d) is not None]
        if not starts:
            continue
        with ledger_session() as db:
            have = {cid for (cid,) in db.query(Change.id).filter(Change.session_id == sid)}
            unpriced = {cid for (cid,) in db.query(Change.id).filter(
                Change.session_id == sid, Change.cost_usd.is_(None),
                Change.tok_in + Change.tok_out + Change.tok_cache_read + Change.tok_cache_write > 0)}
        if unpriced and not dry_run:
            _reprice(tp, sid, lines, starts, unpriced, proj.id)
        new = [k for k, i in enumerate(starts) if _cid(sid, lines[i][1]) not in have]
        if not new:
            if not dry_run:
                _close_if_quiet(sid, lines, proj.id)
            continue
        res.sessions += 1
        res.changes += len(new)
        if dry_run:
            for k in new:
                end = lines[starts[k + 1]][0] if k + 1 < len(starts) else None
                res.cost_usd += pricing.cost(parse_turn(tp, lines[starts[k]][0], end).usage)[0] or 0
            continue
        res.cost_usd += _import_session(tp, sid, lines, starts, set(new), proj, cfg, pcfg)
    if not dry_run and res.sessions:
        audit.record_head()
    res.cost_usd = round(res.cost_usd, 4)
    return res


def _reprice(tp: Path, sid: str, lines: list[tuple[int, dict[str, Any]]], starts: list[int], cids: set[str], pid: str) -> None:
    """Price turns that were recorded without a cost. The ledger row gets the cost; the audit trail gets a new event."""
    events = []
    with ledger_session() as db:
        for k, i in enumerate(starts):
            cid = _cid(sid, lines[i][1])
            if cid not in cids or (row := db.get(Change, cid)) is None:
                continue
            end = lines[starts[k + 1]][0] if k + 1 < len(starts) else None
            cost, version = pricing.cost(parse_turn(tp, lines[i][0], end).usage)
            if cost is None:
                continue
            row.cost_usd, row.price_version = cost, version
            events.append({**ingest._ctx(sid, pid), "event_id": f"imp:{sid}:{cid}:repriced:{version}", "type": "change.repriced",
                           "actor_kind": "system", "subject": cid, "occurred_at": spool.now(),
                           "detail": {"cost_usd": cost, "price_version": version}})
        db.commit()
    if events:
        audit.append(ingest._fresh(events))


def _entrypoint(tp: Path) -> str | None:
    """The first entrypoint field, read line by line: a long session's transcript can be over 100 MB."""
    try:
        with open(tp, encoding="utf-8") as fh:
            for ln in fh:
                if '"entrypoint"' in ln:
                    try:
                        ep = json.loads(ln).get("entrypoint")
                    except json.JSONDecodeError:
                        continue
                    if isinstance(ep, str):
                        return ep[:40]
    except OSError:
        pass
    return None


def _cid(sid: str, first: dict[str, Any]) -> str:
    return ingest.change_id(sid, first.get("promptId") or first.get("uuid"), str(first.get("timestamp") or ""))


def _ended(lines: list[tuple[int, dict[str, Any]]]) -> str | None:
    """Last timestamp once the transcript has been quiet for QUIET; None while it may still be running."""
    last = next((str(d["timestamp"]) for _, d in reversed(lines) if d.get("timestamp")), None)
    if not last:
        return None
    t = datetime.fromisoformat(last.replace("Z", "+00:00"))
    return last if datetime.now(UTC) - t > QUIET else None


def _close_if_quiet(sid: str, lines: list[tuple[int, dict[str, Any]]], pid: str) -> None:
    end = _ended(lines)
    if end is None:
        return
    with ledger_session() as db:
        s = db.get(Session, sid)
        if s is None or s.ended_at:
            return
        s.ended_at = end
        db.commit()
    audit.append(ingest._fresh([{**ingest._ctx(sid, pid), "event_id": f"imp:{sid}:end", "type": "session.end",
                                 "actor_kind": "system", "occurred_at": end, "detail": {"imported": True}}]))


def _import_session(tp: Path, sid: str, lines: list[tuple[int, dict[str, Any]]], starts: list[int], new: set[int],
                    proj: Any, cfg: dict[str, Any], pcfg: dict[str, Any]) -> float:
    pid, root = proj.id, proj.root
    stamps = [str(d.get("timestamp")) for _, d in lines if d.get("timestamp")]
    version = next((str(d["version"]) for _, d in lines if d.get("version")), None)
    base = ingest._ctx(sid, pid)
    events: list[dict[str, Any]] = [{**base, "event_id": f"imp:{sid}:start", "type": "session.start", "actor_kind": "system",
                                     "subject": proj.name, "occurred_at": stamps[0],
                                     "detail": {"imported": True, "tool_version": version}}]
    inv_by_id = {s["id"]: s for s in ingest.inventory(pid)}
    lk = lock.load(root)
    pols = policy.load(root)
    total = 0.0
    with ledger_session() as db:
        if db.get(Project, pid) is None:
            db.add(Project(id=pid, name=proj.name, remote=proj.remote, root_path=root, created_at=stamps[0]))
        if db.get(Session, sid) is None:
            db.add(Session(id=sid, project_id=pid, started_at=stamps[0], tool="claude-code", tool_version=version,
                           user_id=ingest._user_id(), source="imported",
                           entrypoint=next((str(d["entrypoint"])[:40] for _, d in lines if d.get("entrypoint")), None)))
        for k, i in enumerate(starts):
            if k not in new:
                continue
            off, first = lines[i]
            j = starts[k + 1] if k + 1 < len(starts) else len(lines)
            end = lines[j][0] if j < len(lines) else None
            slice_ = [d for _, d in lines[i:j]]
            prompt = _prompt_of(first) or ""
            t0 = str(first.get("timestamp") or stamps[0])
            t1 = next((str(d["timestamp"]) for d in reversed(slice_) if d.get("timestamp")), t0)
            cid = _cid(sid, first)
            t = parse_turn(tp, off, end)
            cost, price_version = pricing.cost(t.usage)
            total += cost or 0
            calls, files = _tools(slice_, root)
            store = cfg["store_prompt_text"]
            stored = prompt if store == "full" else redact(prompt, allow_values=pcfg["allow_values"],
                                                              custom_rules=pcfg["custom_rules"]) if store == "redacted" else None
            db.add(Change(id=cid, session_id=sid, project_id=pid, seq=k + 1, started_at=t0, ended_at=t1,
                          duration_s=ingest._secs(t0, t1), prompt_text=stored,
                          summary=redact(summarise(t.last_text)) if t.last_text else None, model=ingest._main_model(t),
                          tok_in=ingest._sum(t, "tok_in"), tok_out=ingest._sum(t, "tok_out"),
                          tok_cache_read=ingest._sum(t, "tok_cache_read"), tok_cache_write=ingest._sum(t, "tok_cache_write"),
                          cost_usd=cost, price_version=price_version))
            db.flush()
            for path, (a, r) in sorted(files.items()):
                db.add(ChangeFile(change_id=cid, path=path, added=a, removed=r))
            pii_lines = []
            if cfg["mode"] != "off":
                found, _ = scan_with_stats(prompt, only=cfg["types"] + ["custom"], allow_values=pcfg["allow_values"],
                                           custom_rules=pcfg["custom_rules"], min_confidence="low")
                pii_lines = [{"ev": "pii_prompt", "blocked": False, "findings": [
                    {"type": f.type, "confidence": f.confidence, "count": f.count, "distinct": f.distinct,
                     "detector": f.detector, "fingerprints": f.fingerprints} for f in found]}] if found else []
                c = stopscan.Collector(cfg, pcfg)
                stopscan.scan_transcript(c, t, root)
                ingest._write_stop_pii(db, cid, list(c.rows.values()))
            ingest._write_prompt_pii(db, cid, pii_lines)
            invs = reconcile([], t, prompt, inv_by_id)
            for inv in invs:
                inv.status = lock.status(lk, inv.skill_id, inv.hash)
            ingest._write_invocations(db, cid, invs)
            results = policy.evaluate(pols, sorted(files), {x.skill_id for x in invs if x.status != "blocked"})
            ingest._write_policies(db, cid, pid, pols, results)
            ev = ingest._ctx(sid, pid, cid)
            events.append({**ev, "event_id": f"imp:{cid}:turn.start", "type": "turn.start", "actor_kind": "user",
                           "occurred_at": t0, "detail": {"imported": True}})
            events += [{**ev, "event_id": f"imp:{cid}:tool:{n}", "type": "tool.call", "actor_kind": "agent", "subject": name,
                        "occurred_at": ts or t0, "detail": {"tool": name, "path": path}} for n, (ts, name, path) in enumerate(calls)]
            events += [{**ev, "event_id": f"imp:{cid}:file:{path}", "type": "file.changed", "actor_kind": "agent", "subject": path,
                        "occurred_at": t1, "detail": {"path": path, "added": a, "removed": r}} for path, (a, r) in sorted(files.items())]
            events += [{**ev, "event_id": f"imp:{cid}:skill:{n}", "type": "skill.invoked", "actor_kind": "agent",
                        "subject": inv.skill_id, "occurred_at": t1,
                        "detail": {"skill": inv.skill_id, "hash": (inv.hash or "")[:12] or None, "trigger": inv.trigger,
                                   "status": inv.status}} for n, inv in enumerate(invs, 1)]
            events += [{**ev, "event_id": f"imp:{cid}:policy:{pol_id}", "type": "policy.result", "actor_kind": "system",
                        "subject": pol_id, "outcome": "ok" if met else "failed", "occurred_at": t1,
                        "detail": {"policy": pol_id, "met": met}} for pol_id, met in results]
            events.append({**ev, "event_id": f"imp:{cid}:turn.end", "type": "turn.end", "actor_kind": "agent", "occurred_at": t1,
                           "detail": {"imported": True, "tok_in": ingest._sum(t, "tok_in"), "tok_out": ingest._sum(t, "tok_out"),
                                      "tok_cache_read": ingest._sum(t, "tok_cache_read"),
                                      "tok_cache_write": ingest._sum(t, "tok_cache_write"), "cost_usd": cost,
                                      "price_version": price_version, "files": len(files)}})
        db.commit()
        from .db.models import PiiFinding

        for f in db.query(PiiFinding).join(Change, Change.id == PiiFinding.change_id).filter(Change.session_id == sid):
            events.append({**ingest._ctx(sid, pid, f.change_id), "event_id": f"imp:{f.change_id}:pii:{f.id}", "type": "pii.finding",
                           "actor_kind": "hook", "subject": f.type, "occurred_at": stamps[-1],
                           "detail": {"finding": f.id, "type": f.type, "count": f.count, "confidence": f.confidence,
                                      "destination": f.destination, "source_kind": f.source_kind}})
    audit.append(ingest._fresh(events))
    _close_if_quiet(sid, lines, pid)
    return total
