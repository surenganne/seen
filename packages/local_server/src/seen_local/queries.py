"""Read-side queries over the ledger. Local scale (thousands of changes): load a project's rows
once per request and filter in Python.
ponytail: O(n) per request; move filters into SQL if a project passes ~50k changes."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from seen_core import pricing
from seen_core.db.models import (
    Change,
    ChangeFile,
    PiiFinding,
    Policy,
    PolicyResult,
    Project,
    Session,
    Skill,
    SkillInvocation,
    SkillVersion,
)
from seen_core.skills import lock

from . import schemas as S

TZ_OFFSET = timedelta(minutes=330)  # display dates in IST
HIGH_PII = {"aadhaar", "card", "iban", "secret"}


@dataclass
class Row:
    c: Change
    tool: str = "claude-code"
    background: bool = False
    files: list[ChangeFile] = field(default_factory=list)
    skills: list[SkillInvocation] = field(default_factory=list)
    policies: list[PolicyResult] = field(default_factory=list)
    pii: list[PiiFinding] = field(default_factory=list)

    def out(self) -> S.ChangeRow:
        c = self.c
        return S.ChangeRow(
            id=c.id, seq=c.seq, session_id=c.session_id, started_at=c.started_at,
            request=request_line(c.prompt_text), summary=c.summary,
            background=self.background, model=c.model,
            tool=self.tool, files=[f.path for f in self.files], added=sum(f.added for f in self.files),
            removed=sum(f.removed for f in self.files), tokens=c.tok_in + c.tok_out + c.tok_cache_read + c.tok_cache_write,
            cost_usd=c.cost_usd or 0.0, git_status=c.git_status,
            skills=[s.skill_id or "" for s in self.skills], policy_missed=any(not p.met for p in self.policies),
            pii_state=c.pii_state, pii_count=sum(p.count for p in self.pii if p.status == "open") if self.pii else c.pii_count,
            pii_high=any(p.confidence == "high" and p.status == "open" for p in self.pii),
            unapproved_skill=any(s.status in ("changed", "unreviewed", "blocked") for s in self.skills))


_TAG = re.compile(r"<(command-name|command-args|summary)>(.*?)</\1>", re.S)


def request_line(prompt: str | None) -> str | None:
    """The request on one line. Text Claude Code injects reads as what it is, not as raw tags."""
    if not prompt:
        return None
    tags = {k: " ".join(v.split()) for k, v in _TAG.findall(prompt)}
    if prompt.lstrip().startswith("<task-notification>"):
        return "Automatic follow-up: a background task finished" + (f" ({tags['summary'][:300]})" if tags.get("summary") else "")
    if tags.get("command-name"):
        return " ".join(x for x in (tags["command-name"], tags.get("command-args", "")) if x)[:400]
    return " ".join(prompt.split())[:400]


PII_CHECKED = ("Structured identifiers (email, phone, Aadhaar, PAN, card, IBAN, SSN, UPI, DOB, GSTIN, passport, secrets) in the "
               "prompt, file reads, tool and MCP output, network tool inputs and added diff lines. "
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
    sess = {sid: (tool, ep) for sid, tool, ep in db.execute(
        select(Session.id, Session.tool, Session.entrypoint).where(Session.project_id == pid)).all()}
    for r in rows.values():
        tool, ep = sess.get(r.c.session_id or "", (None, None))
        r.tool = tool or "claude-code"
        r.background = bool(ep and ep.startswith("sdk"))
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


def _tiles(rows: list[Row], bg: list[Row]) -> S.Tiles:
    """The headline figures for a set of requests. PII and policy counts follow the same rules as the page: PII covers
    every session, everything else only the person's own requests."""
    outs = [r.out() for r in rows]
    every_out = outs + [r.out() for r in bg]
    changed = [r for r in rows if r.files]
    results = [p for r in rows for p in r.policies]
    return S.Tiles(
        changes=len(rows), changed=len(changed),
        commits=len({r.c.git_head_after for r in changed if r.c.git_status == "committed" and r.c.git_head_after}),
        files_changed=len({f.path for r in rows for f in r.files}), lines_added=sum(o.added for o in outs),
        lines_removed=sum(o.removed for o in outs), tokens=sum(o.tokens for o in outs),
        tok_in=sum(r.c.tok_in for r in rows), tok_out=sum(r.c.tok_out for r in rows),
        tok_cache_read=sum(r.c.tok_cache_read for r in rows), tok_cache_write=sum(r.c.tok_cache_write for r in rows),
        cost_usd=round(sum(o.cost_usd for o in outs), 4), policy_checks=len(results), policy_met=sum(bool(p.met) for p in results),
        policy_missed=sum(o.policy_missed for o in outs), pii_changes=sum(o.pii_count > 0 for o in every_out),
        pii_high=sum(o.pii_high for o in every_out), background_changes=len(bg),
        background_cost_usd=round(sum(r.c.cost_usd or 0 for r in bg), 4))


def overview(db: DB, pid: str, days: int, audit_ok: bool) -> S.Overview:
    both = load_rows(db, pid, days * 2)  # this period and the one before it, for the deltas
    cut = since(days)
    every = [r for r in both if (r.c.started_at or "") >= cut]
    before = [r for r in both if (r.c.started_at or "") < cut]
    rows = [r for r in every if not r.background]  # the person's requests; PII and the alert still count every session
    bg = [r for r in every if r.background]
    today = (datetime.now(UTC) + TZ_OFFSET).date()
    per_day: dict[str, list[Row]] = {(today - timedelta(days=i)).isoformat(): [] for i in range(days - 1, -1, -1)}
    for r in every:
        d = _day(r.c.started_at or "")
        if d in per_day and not r.background:
            per_day[d].append(r)
    pii_day = Counter(_day(r.c.started_at or "") for r in every if r.out().pii_count > 0)
    by_day = []
    for d, rs in per_day.items():
        cbm: dict[str, float] = defaultdict(float)
        for r in rs:
            cbm[r.c.model or "unknown"] += r.c.cost_usd or 0
        changed = [r for r in rs if r.files]
        by_day.append(S.DayStat(
            date=d, requests=len(rs), changed=len(changed), files=len({f.path for r in rs for f in r.files}),
            added=sum(f.added for r in rs for f in r.files), removed=sum(f.removed for r in rs for f in r.files),
            commits=len({r.c.git_head_after for r in changed if r.c.git_status == "committed" and r.c.git_head_after}),
            cost_usd=round(sum(cbm.values()), 6), cost_by_model={m: round(v, 6) for m, v in cbm.items() if v},
            tok_out=sum(r.c.tok_out for r in rs), pii_changes=pii_day[d]))
    git = S.GitOutcomes(**{k: sum(1 for r in rows if r.files and r.c.git_status == k) for k in ("committed", "uncommitted", "reverted")})
    area_stats: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        mine: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for f in r.files:
            a = areas_of([f.path])[0]
            mine[a][0] += f.added
            mine[a][1] += f.removed
        for a, (add, rem) in mine.items():
            s = area_stats[a]
            s[0] += 1
            s[1] += add
            s[2] += rem
    skills = Counter(s.skill_id for r in rows for s in r.skills if s.skill_id)
    skill_status = dict(Counter(s.status for r in rows for s in r.skills if s.status))
    pols = {p.id: p for p in db.scalars(select(Policy).where(Policy.project_id == pid))}
    checks: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        for p in r.policies:
            checks[p.policy_id][0] += 1
            checks[p.policy_id][1] += bool(p.met)
    policies = [S.PolicyStat(policy_id=k, title=pols[k].title if k in pols else None,
                             require_skill=pols[k].require_skill if k in pols else None, mode=pols[k].mode if k in pols else None,
                             checks=v[0], met=v[1]) for k, v in sorted(checks.items(), key=lambda x: -x[1][0])]
    rhythm: Counter[tuple[int, int]] = Counter()
    for r in rows:
        if r.c.started_at:
            t = datetime.fromisoformat(r.c.started_at.replace("Z", "+00:00")) + TZ_OFFSET
            rhythm[(t.weekday(), t.hour)] += 1
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
    findings = [p for r in every for p in r.pii if p.status == "open"]
    by_type: dict[str, list[Any]] = defaultdict(lambda: [0, set()])
    sources: dict[tuple[str, str], list[Any]] = defaultdict(lambda: [set(), 0, set()])
    for p in findings:
        by_type[p.type or "?"][0] += p.count
        by_type[p.type or "?"][1].add(p.change_id)
        s = sources[(p.source_kind or "", p.source_ref or "")]
        s[0].add(p.change_id)
        s[1] += p.count
        s[2].add(p.type)
    return S.Overview(
        range=days, tiles=_tiles(rows, bg), prev=_tiles([r for r in before if not r.background], [r for r in before if r.background]),
        by_day=by_day, git=git, policies=policies, skill_status=skill_status,
        areas=[S.AreaStat(area=a, changes=v[0], added=v[1], removed=v[2]) for a, v in sorted(area_stats.items(), key=lambda x: -x[1][0])[:8]],
        rhythm=[S.RhythmCell(dow=d, hour=h, changes=n) for (d, h), n in sorted(rhythm.items())],
        top_skills=[S.SkillStat(skill_id=s, runs=n) for s, n in skills.most_common(10)],
        by_model=sorted(models.values(), key=lambda m: -m.cost_usd),
        pii_by_type=[S.PiiTypeStat(type=t, count=v[0], changes=len(v[1])) for t, v in sorted(by_type.items(), key=lambda x: -x[1][0])],
        pii_top_sources=[S.PiiSource(source_kind=k, source_ref=ref, changes=len(v[0]), count=v[1], types=sorted(v[2]),
                                     deny_rule=deny_rule(k, ref))
                         for (k, ref), v in sorted(sources.items(), key=lambda x: -len(x[1][0]))[:8]],
        alert=alert(every, audit_ok))


SORTS = {"time": lambda o: o.started_at or "", "cost": lambda o: o.cost_usd, "tokens": lambda o: o.tokens,
         "files": lambda o: len(o.files), "lines": lambda o: o.added + o.removed, "seq": lambda o: o.seq or 0}


def changes(db: DB, pid: str, *, tool: str | None, status: str | None, q: str | None, file: str | None, skill: str | None,
            policy_missed: bool | None, pii: bool | None, days: int | None, sort: str, dir: str,
            session: str | None = None, kind: str = "all", page: int = 1, page_size: int = 50) -> S.ChangePage:
    outs = [r.out() for r in load_rows(db, pid, days)]
    bg = sum(o.background for o in outs)
    counts = S.SessionCounts(all=len(outs), yours=len(outs) - bg, background=bg)
    if kind in ("yours", "background") and not session:  # a session link shows that session whatever its kind
        outs = [o for o in outs if o.background == (kind == "background")]
    if session:
        outs = [o for o in outs if o.session_id == session]
    if tool:
        outs = [o for o in outs if o.tool == tool]
    if status:
        outs = [o for o in outs if o.git_status == status]
    if q:
        ql = q.lower()
        outs = [o for o in outs if ql in (o.summary or "").lower() or ql in (o.request or "").lower()
                or any(ql in f.lower() for f in o.files)]
    if file:
        outs = [o for o in outs if file in o.files]
    if skill:
        outs = [o for o in outs if skill in o.skills]
    if policy_missed:
        outs = [o for o in outs if o.policy_missed]
    if pii:
        outs = [o for o in outs if o.pii_count > 0]
    outs.sort(key=SORTS.get(sort, SORTS["time"]), reverse=dir != "asc")
    return S.ChangePage(total=len(outs), counts=counts, page=page, page_size=page_size, cost_usd=round(sum(o.cost_usd for o in outs), 4),
                        items=outs[(page - 1) * page_size: page * page_size])


def _actors(pid: str) -> dict[str, str]:
    """change id -> actor id, from the audit trail (the ledger rows carry no user)."""
    import sqlite3

    from seen_core import paths

    try:
        con = sqlite3.connect(f"file:{paths.audit_db()}?mode=ro", uri=True)
        try:
            return {cid: a for cid, a in con.execute(
                "SELECT change_id, MIN(actor_id) FROM audit_events WHERE project_id = ? AND change_id IS NOT NULL "
                "AND actor_id IS NOT NULL GROUP BY change_id", (pid,))}
        finally:
            con.close()
    except sqlite3.Error:
        return {}


def areas_of(paths: list[str]) -> list[str]:
    """Top folders a change touched: two levels deep, a root file as (root). Most files first, ties in first-seen order."""
    def area(p: str) -> str:
        parts = p.strip("/").split("/")
        return "(root)" if len(parts) == 1 else parts[0] if len(parts) == 2 else "/".join(parts[:2])
    return [a for a, _ in Counter(area(p) for p in paths).most_common(3)]


_SENTENCE = re.compile(r"(?<=[.!?])\s")


def headline_of(summary: str | None, request: str | None, files: list[str]) -> str:
    """One line for a change: the first sentence of the reply, else the request, else what was touched."""
    for src in (summary, request):
        text = " ".join((src or "").replace("*", "").replace("`", "").split())
        text = _SENTENCE.split(text, 1)[0] if text else ""
        if len(text) >= 15:
            return text if len(text) <= 140 else text[:139].rstrip() + "…"
    n = len(files)
    return f"Changed {n} {'file' if n == 1 else 'files'} in {', '.join(areas_of(files))}"


def timeline(db: DB, pid: str, *, actor: str | None, days: int | None, all_turns: bool, page: int, page_size: int) -> S.TimelinePage:
    """Changes newest first, grouped by IST day. Paged by entry, so a day can continue on the next page."""
    who = _actors(pid)
    rows = [(r, who.get(r.c.id)) for r in load_rows(db, pid, days)]
    actors = sorted({a for _, a in rows if a})
    rows = [x for x in rows if not actor or x[1] == actor]
    quiet = sum(1 for r, _ in rows if not r.files)
    if not all_turns:
        rows = [x for x in rows if x[0].files]
    rows.sort(key=lambda x: x[0].c.started_at or "", reverse=True)
    by_day: dict[str, list[Row]] = defaultdict(list)
    for r, _ in rows:
        by_day[_day(r.c.started_at) if r.c.started_at else "unknown"].append(r)
    groups: dict[str, list[S.TimelineEntry]] = {}
    for r, a in rows[(page - 1) * page_size: page * page_size]:
        o = r.out()
        paths = [f.path for f in r.files]
        e = S.TimelineEntry(**o.model_dump(), actor=a, commit=(r.c.git_head_after or "")[:7] or None,
                            headline=headline_of(o.summary, o.request, paths), areas=areas_of(paths))
        groups.setdefault(_day(r.c.started_at) if r.c.started_at else "unknown", []).append(e)
    def stats(d: str, es: list[S.TimelineEntry]) -> S.TimelineDay:
        rs = by_day[d]
        return S.TimelineDay(day=d, changes=len(rs), files=len({f.path for r in rs for f in r.files}),
                             added=sum(f.added for r in rs for f in r.files), removed=sum(f.removed for r in rs for f in r.files),
                             commits=len({r.c.git_head_after for r in rs if r.c.git_status == "committed" and r.c.git_head_after}), entries=es)
    return S.TimelinePage(total=len(rows), quiet_hidden=0 if all_turns else quiet, actors=actors, page=page, page_size=page_size,
                          days=[stats(d, es) for d, es in groups.items()])


def change_detail(db: DB, cid: str, prompt_storage: str) -> S.ChangeDetail | None:
    c = db.get(Change, cid)
    if c is None:
        return None
    rows = {r.c.id: r for r in load_rows(db, c.project_id or "")} if c.project_id else {}
    r = rows.get(cid) or Row(c)
    model_prices = pricing.table()["models"].get(c.model or "", None)
    parts: list[S.CostPart] = []
    if model_prices:
        raw = [("input", c.tok_in, model_prices["input"]), ("output", c.tok_out, model_prices["output"]),
               ("cache_read", c.tok_cache_read, model_prices["cache_read"]), ("cache_write", c.tok_cache_write, model_prices["cache_write_5m"])]
        total = sum(n * p for _, n, p in raw) or 1
        parts = [S.CostPart(kind=k, tokens=n, cost_usd=round(n * p / 1e6, 6), share=round(n * p / total, 4)) for k, n, p in raw]  # type: ignore[arg-type]
    pols = {p.id: p for p in db.scalars(select(Policy).where(Policy.project_id == c.project_id))}
    kinds = dict(db.execute(select(Skill.id, Skill.kind)).all())
    sess = db.get(Session, c.session_id) if c.session_id else None
    return S.ChangeDetail(
        source="imported" if sess is not None and sess.source == "imported" else "live",
        id=c.id, project_id=c.project_id, session_id=c.session_id, seq=c.seq, started_at=c.started_at, ended_at=c.ended_at,
        duration_s=c.duration_s, summary=c.summary, prompt_text=c.prompt_text, prompt_storage=prompt_storage, model=c.model,
        tool=r.tool, tokens=S.Tokens(input=c.tok_in, out=c.tok_out, cache_read=c.tok_cache_read, cache_write=c.tok_cache_write),
        cost_usd=c.cost_usd, price_version=c.price_version, prices_verified=bool(pricing.table().get("verified")),
        cost_breakdown=parts, git_head_before=c.git_head_before, git_head_after=c.git_head_after, git_status=c.git_status,
        files=[S.FileLine(path=f.path, added=f.added, removed=f.removed) for f in r.files],
        skills=[S.SkillRun(ordinal=s.ordinal, skill_id=s.skill_id or "", kind=kinds.get(s.skill_id), hash_short=(s.hash or "")[:7] or None,
                           trigger=s.trigger, status=s.status) for s in r.skills],
        policies=[S.PolicyCheck(policy_id=p.policy_id, title=pols[p.policy_id].title if p.policy_id in pols else None,
                                require_skill=pols[p.policy_id].require_skill if p.policy_id in pols else None, met=bool(p.met),
                                mode=pols[p.policy_id].mode if p.policy_id in pols else None) for p in r.policies],
        pii=[pii_out(p) for p in r.pii],
        pii_checked=PII_CHECKED)


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
    out.sort(key=lambda o: o.id)
    out.sort(key=lambda o: o.last_used or "", reverse=True)  # most recently used first, never-used last (by name)
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
        recent = bool(last and last >= cutoff)
        # an imported transcript that has gone quiet has ended; only live sessions can be cut off mid-way
        status = "ended" if s.ended_at or (s.source == "imported" and not recent) else "active" if recent else "incomplete"
        out.append(S.SessionOut(id=s.id, started_at=s.started_at, ended_at=s.ended_at, status=status,
                                source="imported" if s.source == "imported" else "live", last_event_at=last,
                                tool=s.tool, tool_version=s.tool_version, entrypoint=s.entrypoint,
                                background=bool(s.entrypoint and s.entrypoint.startswith("sdk")), models=sorted({c.model for c in cs if c.model}),
                                turns=len(cs), files=files[s.id], tool_calls=calls, events=n,
                                cost_usd=round(sum(c.cost_usd or 0 for c in cs), 4)))
    return sorted(out, key=lambda x: x.started_at or "", reverse=True)
