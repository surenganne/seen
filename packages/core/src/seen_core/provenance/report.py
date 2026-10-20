"""`seen pr-report`: who wrote the lines a branch adds (spec sections 6, 7.1, 8, 9).

Read side only. Refs and the diff come from an untrusted repo: refs are checked by pattern, git runs through
`gitutil` with `--end-of-options`. Never stores or prints line text, and never uses the prompt (a posted report
leaves the machine): request headlines come from the redacted assistant summary only."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa

from .. import gitutil, secret
from ..db.models import Change, ChangeFile, PiiFinding, Policy, PolicyResult, SkillInvocation
from ..headline import clean, headline_of
from ..pii.checked import PII_CHECKED
from . import blame
from .prints import fingerprint, is_trivial, normalize

CHUNK = 900  # SQLite allows 999 variables per statement
FAIL_ON = ("rule-missed", "pii-high", "unapproved-skill")
MAX_REQUESTS_SHOWN = 10
_HUNK = re.compile(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
_PII_ORDER = {"none": 0, "found": 1, "blocked": 2}


@dataclass(frozen=True)
class RequestRef:
    change_id: str
    headline: str
    started_at: str | None
    model: str | None


@dataclass
class Report:
    base: str
    head: str
    commits: int
    added: dict[str, int]  # agent, human, not_observed (neutral lines are counted apart)
    requests: list[RequestRef]
    sessions: int
    models: list[str]
    skills: list[tuple[str, str]]  # (id, approval status when it ran)
    rules_missed: int
    pii_state: str
    pii_checked: str
    cost_usd: float | None
    neutral: int = 0  # blank or punctuation-only added lines, left out of the percentages
    files: int = 0
    missed_rules: list[str] = field(default_factory=list)
    rules_checked: int = 0
    pii_high: int = 0
    pii_unchecked: int = 0  # attributing changes whose PII state was never recorded


def parse_diff_added(diff_text: str) -> dict[str, list[str]]:
    """Added lines per path from `git diff --unified=0 -M`. Binary files and deletions have none. Hunk line counts
    decide what is content, so an added line that reads `++ b/x` cannot pass for a file header."""
    out: dict[str, list[str]] = {}
    path: str | None = None
    old_left = new_left = 0
    for ln in diff_text.split("\n"):
        if old_left or new_left:
            if ln.startswith("+"):
                new_left -= 1
                if path is not None:
                    out[path].append(blame.SURROGATE.sub("�", ln[1:].removesuffix("\r")))
            elif ln.startswith("-"):
                old_left -= 1
            # "\ No newline at end of file" and anything else costs nothing
            continue
        if ln.startswith("diff --git "):
            path = None
        elif ln.startswith("+++ "):
            p = blame.unquote(ln[4:].split("\t")[0])
            path = p[2:] if p.startswith("b/") else None  # /dev/null: a deletion
            if path is not None:
                out.setdefault(path, [])
        elif m := _HUNK.match(ln):
            old_left = 1 if m[1] is None else int(m[1])
            new_left = 1 if m[2] is None else int(m[2])
    return {p: v for p, v in out.items() if v}


def _chunks(items: list[str]) -> list[list[str]]:
    return [items[i:i + CHUNK] for i in range(0, len(items), CHUNK)]


def _git(root: str, *args: str, what: str) -> str:
    out = gitutil.run_raw(root, *args)
    if out is None:
        raise ValueError(what)
    return out


def build_report(db: Any, project: Any, base: str, head: str = "HEAD", with_cost: bool = True) -> Report:
    """Raises ValueError for an unsafe or unknown ref, or a project without a repo root."""
    root = project.root_path
    if not root:
        raise ValueError("project has no repo root")
    for ref in (base, head):
        if not blame.REV.fullmatch(ref):
            raise ValueError("unsafe ref")
    rng = f"{base}...{head}"
    for ref in (base, head):  # tell an unknown ref from a timeout or a failed diff
        if gitutil.run_raw(root, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}") is None:
            raise ValueError(f"unknown ref {clean(ref)!r}")
    timed_out = f"timed out reading the diff of {rng}"
    diff = _git(root, "diff", "--unified=0", "-M", "--end-of-options", rng, "--", what=timed_out)
    numstat = _git(root, "diff", "--numstat", "-M", "--end-of-options", rng, "--", what=timed_out)
    commits = _git(root, "rev-list", "--count", "--end-of-options", f"{base}..{head}", "--", what=timed_out).strip()
    head_time = _git(root, "log", "-1", "--format=%ct", "--end-of-options", head, "--", what=timed_out).strip()
    added = parse_diff_added(diff)
    expect = sum(int(x.split("\t")[0]) for x in numstat.split("\n") if x.split("\t")[0].isdecimal())
    if sum(len(v) for v in added.values()) != expect:  # fail closed: never a report with lines missing
        raise ValueError(f"could not parse the diff of {rng}")

    index: blame.Index = {}
    for chunk in _chunks(sorted(added)):
        index.update(blame.load_index(db, project.id, set(chunk)))
    first = blame.epoch(db.scalar(sa.select(sa.func.min(Change.started_at)).where(Change.project_id == project.id)))
    # a range whose newest commit is older than the first recorded change cannot have been seen (spec 6.4)
    pre_seen = first is None or (head_time.isdigit() and int(head_time) < math.floor(first))
    key = secret.key()
    counts = {"agent": 0, "human": 0, "not_observed": 0}
    neutral = 0
    chosen: set[str] = set()
    for path, texts in added.items():
        for text in texts:
            if not normalize(text) or is_trivial(text):
                neutral += 1  # no blame time in a diff, so spec 6.3 adjacency does not apply here
            elif cands := index.get((path, fingerprint(text, key))):
                counts["agent"] += 1
                chosen.add(max(cands, key=lambda c: (c[1], c[0]))[0])  # latest ended_at wins a tie
            else:
                counts["not_observed" if pre_seen else "human"] += 1

    r = Report(base, head, int(commits) if commits.isdigit() else 0, counts, [], 0, [], [], 0, "none", PII_CHECKED, None,
               neutral, len(added))
    _enrich(db, r, sorted(chosen), with_cost)
    return r


def _enrich(db: Any, r: Report, ids: list[str], with_cost: bool) -> None:
    changes: list[Change] = []
    files: dict[str, list[str]] = {i: [] for i in ids}
    skills: set[tuple[str, str]] = set()
    titles: dict[str, str] = {}
    pii_high = 0
    for chunk in _chunks(ids):
        changes += db.scalars(sa.select(Change).where(Change.id.in_(chunk)))
        for cid, p in db.execute(sa.select(ChangeFile.change_id, ChangeFile.path).where(ChangeFile.change_id.in_(chunk))
                                 .order_by(ChangeFile.path)):
            files[cid].append(p)
        skills.update((s, st or "unknown") for s, st in db.execute(
            sa.select(SkillInvocation.skill_id, SkillInvocation.status).where(SkillInvocation.change_id.in_(chunk)))
            if s)
        for met, pid, title in db.execute(
                sa.select(PolicyResult.met, PolicyResult.policy_id, Policy.title)
                .outerjoin(Policy, Policy.id == PolicyResult.policy_id).where(PolicyResult.change_id.in_(chunk))):
            r.rules_checked += 1
            if not met:
                r.rules_missed += 1
                titles[pid] = title or pid
        pii_high += db.scalar(sa.select(sa.func.count()).select_from(PiiFinding).where(
            PiiFinding.change_id.in_(chunk), PiiFinding.confidence == "high", PiiFinding.status == "open")) or 0
    changes.sort(key=lambda c: (c.started_at or "", c.id))
    r.requests = [RequestRef(c.id, headline_of(c.summary, None, files[c.id]), c.started_at, c.model) for c in changes]
    r.sessions = len({c.session_id for c in changes})
    r.models = sorted({c.model for c in changes if c.model})
    r.skills = sorted(skills)
    r.missed_rules = sorted(titles.values())
    r.pii_high = pii_high
    states = [c.pii_state for c in changes if c.pii_state in _PII_ORDER]
    r.pii_unchecked = len(changes) - len(states)
    r.pii_state = max(states, key=_PII_ORDER.__getitem__, default="none")
    if r.pii_unchecked and r.pii_state == "none":
        r.pii_state = "unknown"  # never "none" while some request was not checked
    if with_cost:
        costs = [c.cost_usd for c in changes if c.cost_usd is not None]
        r.cost_usd = sum(costs) if costs else None


def _c(s: str | None) -> str:
    """A model- or ledger-derived string as an inline code span: GitHub then acts on no @mention, #N, link or HTML."""
    return f"`{clean(s).replace('`', chr(39)) or '-'}`"


def _pct(n: int, total: int) -> str:
    return f"{round(100 * n / total)}%" if total else "0%"


def _n(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def render_md(r: Report) -> str:
    """Sections are separated by blank lines so GitHub renders them as paragraphs and one proper list."""
    a = r.added
    total = sum(a.values())
    n = len(r.requests)
    head = (f"AI provenance for {_c(r.head)} ({_n(r.commits, 'commit')} since {_c(r.base)})\n\n"
            f"Added lines: {total + r.neutral} in {_n(r.files, 'file')}, of which {r.neutral} blank or punctuation-only and left "
            f"out of the shares below  ·  agent {a['agent']} ({_pct(a['agent'], total)})  ·  human {a['human']} "
            f"({_pct(a['human'], total)}, an upper bound: it includes code Seen did not see)  ·  not observed "
            f"{a['not_observed']} ({_pct(a['not_observed'], total)})")
    line = f"Requests: {n} in {_n(r.sessions, 'session')}"
    if r.models:
        line += " · " + ", ".join(_c(m) for m in r.models)
    if r.cost_usd is not None:
        line += f" · ${r.cost_usd:.2f} API-equivalent (whole requests, not only the lines kept)"
    items = [f"- {_c(q.headline)}" + (f" ({_c(q.model)})" if q.model else "") for q in r.requests[:MAX_REQUESTS_SHOWN]]
    if n > MAX_REQUESTS_SHOWN:
        items.append(f"- and {n - MAX_REQUESTS_SHOWN} more")
    reqs = "\n".join([line, "", *items]) if items else line
    skills = "Skills: " + (", ".join(f"{_c(s)} ({_c(st)})" for s, st in r.skills) or "none recorded in these requests")
    if r.missed_rules:
        rules = (f"Rules: missed {r.rules_missed} of {r.rules_checked} recorded results: " +
                 ", ".join(_c(t) for t in r.missed_rules))
    else:
        rules = f"Rules: none missed in the {r.rules_checked} recorded rule results of these requests."
    if n == 0:
        res = "no requests were attributed, so PII was not assessed."
    else:
        res = f"Result for these {_n(n, 'request')}: {_c(r.pii_state)}"
        res += f", {_n(r.pii_unchecked, 'request')} not checked" if r.pii_unchecked else ""
        res += f", {r.pii_high} high-confidence open" if r.pii_high else ""
        res += "."
    pii = f"PII: {PII_CHECKED} {res}"
    foot = ("Unattributed lines are human edits or code Seen did not see (Bash-generated, before the plugin, other "
            "machines). Not observed means Seen could not have seen who wrote the line; it is not a claim that a person "
            "wrote it. Checked: git diff of the range, keyed fingerprints of recorded edits.")
    return "\n\n".join([head, reqs, skills, rules, pii, foot]) + "\n"


def gate(r: Report, fail_on: set[str]) -> list[str]:
    reasons = []
    if "rule-missed" in fail_on and r.rules_missed:
        reasons.append(f"rule-missed: {r.rules_missed} rule result(s) not met")
    if "pii-high" in fail_on and r.pii_high:
        reasons.append(f"pii-high: {r.pii_high} high-confidence open PII finding(s) in contributing requests")
    if "unapproved-skill" in fail_on and (bad := [s for s, st in r.skills if st != "approved"]):
        reasons.append(f"unapproved-skill: {len(bad)} skill(s) were not approved when they ran")
    return reasons
