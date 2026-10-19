"""Read-side queries over the ledger. Local scale (thousands of changes): load a project's rows
once per request and filter in Python.
ponytail: O(n) per request; move filters into SQL if a project passes ~50k changes."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from seen_core import pricing
from seen_core.db.models import (
    Change,
    ChangeFile,
    ChangeMemory,
    PiiFinding,
    Policy,
    PolicyResult,
    Project,
    Session,
    Skill,
    SkillInvocation,
    SkillVersion,
)
from seen_core.frontmatter import parse
from seen_core.skills import lock

from . import schemas as S

TZ_OFFSET = timedelta(minutes=330)  # display dates in IST
HIGH_PII = {"aadhaar", "card", "iban", "secret"}


@dataclass
class Row:
    c: Change
    tool: str = "claude-code"
    files: list[ChangeFile] = field(default_factory=list)
    skills: list[SkillInvocation] = field(default_factory=list)
    policies: list[PolicyResult] = field(default_factory=list)
    pii: list[PiiFinding] = field(default_factory=list)

    def out(self) -> S.ChangeRow:
        c = self.c
        return S.ChangeRow(
            id=c.id, seq=c.seq, session_id=c.session_id, started_at=c.started_at, summary=c.summary, model=c.model,
            tool=self.tool, files=[f.path for f in self.files], added=sum(f.added for f in self.files),
            removed=sum(f.removed for f in self.files), tokens=c.tok_in + c.tok_out + c.tok_cache_read + c.tok_cache_write,
            cost_usd=c.cost_usd or 0.0, git_status=c.git_status, mem_state=c.mem_state,
            skills=[s.skill_id or "" for s in self.skills], policy_missed=any(not p.met for p in self.policies),
            pii_state=c.pii_state, pii_count=sum(p.count for p in self.pii if p.status == "open") if self.pii else c.pii_count,
            pii_high=any(p.confidence == "high" and p.status == "open" for p in self.pii),
            unapproved_skill=any(s.status in ("changed", "unreviewed", "blocked") for s in self.skills))


PII_CHECKED = ("Structured identifiers (email, phone, Aadhaar, PAN, card, IBAN, SSN, UPI, DOB, GSTIN, passport, secrets) in the "
               "prompt, file reads, tool and MCP output, network tool inputs, injected memory and added diff lines. "
               "Names, addresses and free-text health details are not detected.")


def pii_out(p: PiiFinding) -> S.PiiFindingOut:
    """Never fingerprints, never values."""
    return S.PiiFindingOut(id=p.id, type=p.type, confidence=p.confidence, count=p.count, distinct_count=p.distinct_count,
                           source_kind=p.source_kind, source_ref=p.source_ref, destination=p.destination, detector=p.detector,
                           status=p.status)


def since(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat().replace("+00:00", "Z")


def load_rows(db: DB, pid: str, days: int | None = None) -> list[Row]:
    q = select(Change).where(Change.project_id == pid)
    if days:
        q = q.where(Change.started_at >= since(days))
    changes = list(db.scalars(q.order_by(Change.started_at.desc())))
    ids = [c.id for c in changes]
    rows = {c.id: Row(c) for c in changes}
    if not ids:
        return []
    tools = dict(db.execute(select(Session.id, Session.tool).where(Session.project_id == pid)).all())
    for r in rows.values():
        r.tool = tools.get(r.c.session_id) or "claude-code"
    for chunk in (ids[i:i + 900] for i in range(0, len(ids), 900)):
        for f in db.scalars(select(ChangeFile).where(ChangeFile.change_id.in_(chunk))):
            rows[f.change_id].files.append(f)
        for s in db.scalars(select(SkillInvocation).where(SkillInvocation.change_id.in_(chunk)).order_by(SkillInvocation.ordinal)):
            rows[s.change_id].skills.append(s)
        for p in db.scalars(select(PolicyResult).where(PolicyResult.change_id.in_(chunk))):
            rows[p.change_id].policies.append(p)
        for p in db.scalars(select(PiiFinding).where(PiiFinding.change_id.in_(chunk))):
            if p.change_id:
                rows[p.change_id].pii.append(p)
    return list(rows.values())


def project_out(db: DB, p: Project) -> S.ProjectOut:
    rows = load_rows(db, p.id)
    last7 = since(7)
    return S.ProjectOut(id=p.id, name=p.name, remote=p.remote, root_path=_redact(p.root_path), changes=len(rows),
                        last_change_at=rows[0].c.started_at if rows else None,
                        cost_7d=round(sum(r.c.cost_usd or 0 for r in rows if (r.c.started_at or "") >= last7), 4),
                        alert=alert(rows).on)


def _redact(p: str | None) -> str | None:
    from seen_core.paths import redact_home

    return redact_home(p) if p else p


def alert(rows: list[Row], audit_ok: bool = True) -> S.Alert:
    reasons = []
    if any(r.out().pii_high for r in rows):
        reasons.append("high-confidence PII exposure")
    if any(r.out().policy_missed for r in rows):
        reasons.append("required skill missed")
    if not audit_ok:
        reasons.append("audit chain failed verification")
    return S.Alert(on=bool(reasons), reasons=reasons)


def _day(ts: str) -> str:
    return (datetime.fromisoformat(ts.replace("Z", "+00:00")) + TZ_OFFSET).date().isoformat()


def deny_rule(source_kind: str, source_ref: str) -> str | None:
    """permissions.deny entry for a file that keeps putting PII into context (syntax from P0-13)."""
    if source_kind == "file_read" and source_ref.startswith("Read "):
        path = source_ref[5:].strip()
        if path and not path.startswith(("/", "~")):
            path = "./" + path
        return f"Read({path})"
    return None


def overview(db: DB, pid: str, days: int, audit_ok: bool) -> S.Overview:
    rows = load_rows(db, pid, days)
    outs = [r.out() for r in rows]
    today = (datetime.now(UTC) + TZ_OFFSET).date()
    by_day: dict[str, dict[str, float]] = {(today - timedelta(days=i)).isoformat(): {} for i in range(days - 1, -1, -1)}
    for r in rows:
        d = _day(r.c.started_at or "")
        if d in by_day:
            by_day[d][r.tool] = round(by_day[d].get(r.tool, 0) + (r.c.cost_usd or 0), 6)
    tools = {r.tool for r in rows} or {"claude-code"}
    for v in by_day.values():
        for t in tools:
            v.setdefault(t, 0.0)
    files: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        for f in r.files:
            s = files[f.path]
            s[0] += 1
            s[1] += f.added
            s[2] += f.removed
    skills = Counter(s.skill_id for r in rows for s in r.skills if s.skill_id)
    models: dict[str, S.ModelStat] = {}
    for r in rows:
        m = models.setdefault(r.c.model or "unknown", S.ModelStat(model=r.c.model or "unknown", changes=0, tok_in=0, tok_out=0,
                                                                   tok_cache_read=0, tok_cache_write=0, cost_usd=0))
        m.changes += 1
        m.tok_in += r.c.tok_in
        m.tok_out += r.c.tok_out
        m.tok_cache_read += r.c.tok_cache_read
        m.tok_cache_write += r.c.tok_cache_write
        m.cost_usd = round(m.cost_usd + (r.c.cost_usd or 0), 6)
    findings = [p for r in rows for p in r.pii if p.status == "open"]
    by_type: dict[str, list[Any]] = defaultdict(lambda: [0, set()])
    sources: dict[tuple[str, str], list[Any]] = defaultdict(lambda: [set(), 0, set()])
    for p in findings:
        by_type[p.type or "?"][0] += p.count
        by_type[p.type or "?"][1].add(p.change_id)
        s = sources[(p.source_kind or "", p.source_ref or "")]
        s[0].add(p.change_id)
        s[1] += p.count
        s[2].add(p.type)
    mem_rows = [o for o in outs if o.mem_state in ("loaded", "missed")]
    tiles = S.Tiles(changes=len(rows), files_changed=len(files), lines_added=sum(o.added for o in outs),
                    lines_removed=sum(o.removed for o in outs), tokens=sum(o.tokens for o in outs),
                    cost_usd=round(sum(o.cost_usd for o in outs), 4),
                    mem_loaded_pct=round(sum(o.mem_state == "loaded" for o in mem_rows) / len(mem_rows), 4) if mem_rows else None,
                    policy_missed=sum(o.policy_missed for o in outs), pii_changes=sum(o.pii_count > 0 for o in outs),
                    pii_high=sum(o.pii_high for o in outs))
    return S.Overview(
        range=days, tiles=tiles, cost_by_day=[S.DayCost(date=d, by_tool=v) for d, v in by_day.items()],
        recent_changes=outs[:8],
        top_files=[S.FileStat(path=p, changes=v[0], added=v[1], removed=v[2]) for p, v in sorted(files.items(), key=lambda x: -x[1][0])[:10]],
        top_skills=[S.SkillStat(skill_id=s, runs=n) for s, n in skills.most_common(10)],
        by_model=sorted(models.values(), key=lambda m: -m.cost_usd),
        pii_by_type=[S.PiiTypeStat(type=t, count=v[0], changes=len(v[1])) for t, v in sorted(by_type.items(), key=lambda x: -x[1][0])],
        pii_top_sources=[S.PiiSource(source_kind=k, source_ref=ref, changes=len(v[0]), count=v[1], types=sorted(v[2]),
                                     deny_rule=deny_rule(k, ref))
                         for (k, ref), v in sorted(sources.items(), key=lambda x: -len(x[1][0]))[:8]],
        alert=alert(rows, audit_ok))


SORTS = {"time": lambda o: o.started_at or "", "cost": lambda o: o.cost_usd, "tokens": lambda o: o.tokens,
         "files": lambda o: len(o.files), "lines": lambda o: o.added + o.removed, "seq": lambda o: o.seq or 0}


def changes(db: DB, pid: str, *, tool: str | None, status: str | None, q: str | None, file: str | None, skill: str | None,
            policy_missed: bool | None, mem: str | None, pii: bool | None, days: int | None, sort: str, dir: str) -> S.ChangePage:
    outs = [r.out() for r in load_rows(db, pid, days)]
    if tool:
        outs = [o for o in outs if o.tool == tool]
    if status:
        outs = [o for o in outs if o.git_status == status]
    if q:
        ql = q.lower()
        outs = [o for o in outs if ql in (o.summary or "").lower() or any(ql in f.lower() for f in o.files)]
    if file:
        outs = [o for o in outs if file in o.files]
    if skill:
        outs = [o for o in outs if skill in o.skills]
    if policy_missed:
        outs = [o for o in outs if o.policy_missed]
    if mem:
        outs = [o for o in outs if o.mem_state == mem]
    if pii:
        outs = [o for o in outs if o.pii_count > 0]
    outs.sort(key=SORTS.get(sort, SORTS["time"]), reverse=dir != "asc")
    return S.ChangePage(total=len(outs), items=outs)


def _memory_files(root: str | None) -> list[tuple[Path, dict[str, Any]]]:
    if not root:
        return []
    d = Path(root) / ".seen" / "memory"
    out = []
    for f in sorted(d.glob("*.md")) if d.is_dir() else []:
        try:
            fm, _ = parse(f.read_text(errors="replace")[:65536])
        except OSError:
            continue
        out.append((f, fm))
    return out


def change_detail(db: DB, cid: str, prompt_storage: str) -> S.ChangeDetail | None:
    c = db.get(Change, cid)
    if c is None:
        return None
    rows = {r.c.id: r for r in load_rows(db, c.project_id or "")} if c.project_id else {}
    r = rows.get(cid) or Row(c)
    proj = db.get(Project, c.project_id) if c.project_id else None
    model_prices = pricing.table()["models"].get(c.model or "", None)
    parts: list[S.CostPart] = []
    if model_prices:
        raw = [("input", c.tok_in, model_prices["input"]), ("output", c.tok_out, model_prices["output"]),
               ("cache_read", c.tok_cache_read, model_prices["cache_read"]), ("cache_write", c.tok_cache_write, model_prices["cache_write_5m"])]
        total = sum(n * p for _, n, p in raw) or 1
        parts = [S.CostPart(kind=k, tokens=n, cost_usd=round(n * p / 1e6, 6), share=round(n * p / total, 4)) for k, n, p in raw]  # type: ignore[arg-type]
    mems = {fm.get("id") or f.stem: fm for f, fm in _memory_files(proj.root_path if proj else None)}
    pols = {p.id: p for p in db.scalars(select(Policy).where(Policy.project_id == c.project_id))}
    kinds = dict(db.execute(select(Skill.id, Skill.kind)).all())
    return S.ChangeDetail(
        id=c.id, project_id=c.project_id, session_id=c.session_id, seq=c.seq, started_at=c.started_at, ended_at=c.ended_at,
        duration_s=c.duration_s, summary=c.summary, prompt_text=c.prompt_text, prompt_storage=prompt_storage, model=c.model,
        tool=r.tool, tokens=S.Tokens(input=c.tok_in, out=c.tok_out, cache_read=c.tok_cache_read, cache_write=c.tok_cache_write),
        cost_usd=c.cost_usd, price_version=c.price_version, prices_verified=bool(pricing.table().get("verified")),
        cost_breakdown=parts, git_head_before=c.git_head_before, git_head_after=c.git_head_after, git_status=c.git_status,
        mem_state=c.mem_state, mem_injected_tokens=c.mem_injected_tokens or 0,
        files=[S.FileLine(path=f.path, added=f.added, removed=f.removed) for f in r.files],
        memories=[S.MemoryRef(memory_id=m.memory_id, content_hash=m.content_hash, type=(mems.get(m.memory_id) or {}).get("type"))
                  for m in db.scalars(select(ChangeMemory).where(ChangeMemory.change_id == cid))],
        skills=[S.SkillRun(ordinal=s.ordinal, skill_id=s.skill_id or "", kind=kinds.get(s.skill_id), hash_short=(s.hash or "")[:7] or None,
                           trigger=s.trigger, status=s.status) for s in r.skills],
        policies=[S.PolicyCheck(policy_id=p.policy_id, title=pols[p.policy_id].title if p.policy_id in pols else None,
                                require_skill=pols[p.policy_id].require_skill if p.policy_id in pols else None, met=bool(p.met),
                                mode=pols[p.policy_id].mode if p.policy_id in pols else None) for p in r.policies],
        pii=[pii_out(p) for p in r.pii],
        pii_checked=PII_CHECKED,
        memory_saved=[str(fm.get("id") or f.stem) for f, fm in _memory_files(proj.root_path if proj else None)
                      if str(fm.get("source_change") or "") == cid])


def _lockfile(db: DB, pid: str | None) -> lock.Lockfile:
    proj = db.get(Project, pid) if pid else None
    return lock.load(proj.root_path) if proj and proj.root_path else lock.Lockfile()


def skills(db: DB, pid: str | None, kind: str | None, status: str | None, q: str | None, unused: bool | None) -> list[S.SkillOut]:
    lk = _lockfile(db, pid)
    latest: dict[str, SkillVersion] = {}
    for v in db.scalars(select(SkillVersion).order_by(SkillVersion.first_seen)):
        latest[v.skill_id] = v
    runs: Counter[str] = Counter()
    last: dict[str, str] = {}
    q_inv = select(SkillInvocation.skill_id, Change.started_at).join(Change, Change.id == SkillInvocation.change_id)
    if pid:
        q_inv = q_inv.where(Change.project_id == pid)
    for sid, ts in db.execute(q_inv):
        runs[sid] += 1
        last[sid] = max(last.get(sid, ""), ts or "")
    out = []
    for s in db.scalars(select(Skill).order_by(Skill.id)):
        if s.kind == "project" and pid and s.scope_project_id not in (None, pid):
            continue
        h = latest[s.id].hash if s.id in latest else None
        st = lock.status(lk, s.id, h)
        o = S.SkillOut(id=s.id, kind=s.kind, origin=s.origin, path=s.path, description=s.description, allowed_tools=s.allowed_tools,
                       hash=h, hash_short=h[:7] if h else None, status=st, runs=runs[s.id], last_used=last.get(s.id),
                       first_seen=s.first_seen)
        if (kind and o.kind != kind) or (status and o.status != status) or (unused and o.runs) or \
                (q and q.lower() not in f"{o.id} {o.description or ''}".lower()):
            continue
        out.append(o)
    return out


def skill_detail(db: DB, sid: str, pid: str | None) -> S.SkillDetail | None:
    base = next((s for s in skills(db, pid, None, None, None, None) if s.id == sid), None)
    if base is None:
        return None
    lk = _lockfile(db, pid)
    approved = lk.approved.get(sid, [])
    inv_q = select(SkillInvocation.hash).where(SkillInvocation.skill_id == sid)
    by_hash = Counter(h for (h,) in db.execute(inv_q))
    versions = [S.SkillVersionOut(hash=v.hash, hash_short=v.hash[:7], first_seen=v.first_seen,
                                  approved=any(v.hash.startswith(a) for a in approved), approved_by=v.approved_by,
                                  approved_at=v.approved_at, runs=by_hash[v.hash])
                for v in db.scalars(select(SkillVersion).where(SkillVersion.skill_id == sid).order_by(SkillVersion.first_seen.desc()))]
    recent = []
    if pid:
        recent = [r.out() for r in load_rows(db, pid) if any(s.skill_id == sid for s in r.skills)][:20]
    req = [p.id for p in db.scalars(select(Policy).where(Policy.require_skill == sid)) if not pid or p.project_id == pid]
    return S.SkillDetail(**base.model_dump(), versions=versions, recent_changes=recent, required_by=req)


def policies(db: DB, pid: str) -> list[S.PolicyOut]:
    out = []
    results = defaultdict(list)
    for pr in db.scalars(select(PolicyResult).join(Change, Change.id == PolicyResult.change_id).where(Change.project_id == pid)):
        results[pr.policy_id].append(pr.met)
    for p in db.scalars(select(Policy).where(Policy.project_id == pid).order_by(Policy.id)):
        r = results.get(p.id, [])
        met = sum(1 for m in r if m)
        out.append(S.PolicyOut(id=p.id, title=p.title, paths=json.loads(p.paths_json or "[]"), require_skill=p.require_skill,
                               mode=p.mode, applicable=len(r), met=met, missed=len(r) - met, compliance=round(met / len(r), 4) if r else 1.0))
    return out


ACTIVE_WINDOW = timedelta(minutes=30)


def sessions(db: DB, pid: str) -> list[S.SessionOut]:
    """Sessions newest first. Active = no session.end yet and an event in the last 30 minutes; incomplete = no end, gone quiet."""
    import sqlite3

    from seen_core import paths

    stats: dict[str, tuple[int, int, str | None]] = {}
    try:
        con = sqlite3.connect(f"file:{paths.audit_db()}?mode=ro", uri=True)
        try:
            for sid, n, calls, last in con.execute(
                    "SELECT session_id, COUNT(*), SUM(type = 'tool.call'), MAX(occurred_at) FROM audit_events "
                    "WHERE project_id = ? AND session_id IS NOT NULL GROUP BY session_id", (pid,)):
                stats[sid] = (n, calls or 0, last)
        finally:
            con.close()
    except sqlite3.Error:
        pass
    by_session: dict[str, list[Change]] = defaultdict(list)
    for c in db.scalars(select(Change).where(Change.project_id == pid)):
        by_session[c.session_id or ""].append(c)
    files: Counter[str] = Counter()
    for sid, _path in db.execute(select(Change.session_id, ChangeFile.path).join(ChangeFile, ChangeFile.change_id == Change.id)
                                .where(Change.project_id == pid).distinct()):
        files[sid or ""] += 1
    cutoff = (datetime.now(UTC) - ACTIVE_WINDOW).isoformat().replace("+00:00", "Z")
    out = []
    for s in db.scalars(select(Session).where(Session.project_id == pid)):
        n, calls, last = stats.get(s.id, (0, 0, None))
        cs = by_session.get(s.id, [])
        last = max([x for x in (last, s.started_at, *(c.ended_at or c.started_at for c in cs)) if x], default=None)
        status = "ended" if s.ended_at else "active" if last and last >= cutoff else "incomplete"
        out.append(S.SessionOut(id=s.id, started_at=s.started_at, ended_at=s.ended_at, status=status, last_event_at=last,
                                tool=s.tool, tool_version=s.tool_version, models=sorted({c.model for c in cs if c.model}),
                                turns=len(cs), files=files[s.id], tool_calls=calls, events=n,
                                cost_usd=round(sum(c.cost_usd or 0 for c in cs), 4)))
    return sorted(out, key=lambda x: x.started_at or "", reverse=True)
