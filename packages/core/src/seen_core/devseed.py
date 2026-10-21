"""`seen dev-seed`: deterministic mock data for development and tests.

Writes only into an explicit SEEN_HOME (never ~/.seen): demo git repos,
lockfile and policies, plus 28 days of sessions, changes, skills, PII findings (types and
counts only, never values) and a valid audit chain.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import audit, paths, pricing, secret
from .db import ledger_session
from .db.models import (
    Change,
    ChangeFile,
    LinePrint,
    PiiFinding,
    Policy,
    PolicyResult,
    Project,
    Session,
    Skill,
    SkillInvocation,
    SkillVersion,
)
from .provenance.prints import fingerprint

PROJECTS = [
    ("payments-api", "github.com/acme/payments-api",
     ["src/payments/charge.py", "src/payments/refund.py", "src/auth/session.py", "src/auth/tokens.py", "api/routes.py",
      "tests/test_charge.py", "llm/summarise.py", "llm/prompts.py", "README.md", "pyproject.toml"]),
    ("patient360-web", "github.com/acme/patient360-web",
     ["src/pages/Patient.tsx", "src/pages/Visits.tsx", "src/api/client.ts", "src/components/Chart.tsx", "data/patients.csv",
      "src/llm/notes.ts", "src/llm/redact.ts", "package.json", "tests/visits.spec.ts"]),
    ("data-pipelines", "github.com/acme/data-pipelines",
     ["dags/daily_sales.py", "dags/kyc_sync.py", "dbt/models/orders.sql", "dbt/models/customers.sql",
      "scripts/backfill.py", "docs/runbook.md"]),
]
SKILLS = [  # id, kind, origin
    ("security-review", "plugin", "everything-claude-code@1.4.0"), ("phi-redaction-check", "project", None),
    ("tdd", "plugin", "superpowers@7.0.0"), ("systematic-debugging", "plugin", "superpowers@7.0.0"),
    ("frontend-design", "plugin", "frontend-design@ea10b21"), ("dataviz", "builtin", None),
    ("quick-sql-helper", "user", None), ("dbt-lint", "project", None), ("release-notes", "user", None),
    ("pii-scan", "org", None), ("api-contract-check", "project", None), ("code-review", "plugin", "code-review@2.1.0"),
    ("perf-audit", "plugin", "agent-skills@0.9.1"), ("airflow-dag-check", "project", None), ("sideloaded-helper", "sideload", None),
]
SUMMARIES = [
    "Added refund idempotency key and tests", "Fixed token refresh race in session middleware",
    "Refactored chart component to use shared axis", "Added daily sales DAG retry policy",
    "Updated LLM summarise prompt to strip identifiers", "Bumped dependencies and fixed lint",
    "Wrote runbook section for backfills", "Added visit list pagination", "Removed dead feature flag",
    "Investigated flaky refund test and pinned clock", "Added dbt test for orders uniqueness",
    "Tightened PHI redaction on clinical notes", "Hardened auth cookie flags", "Cached customer lookup",
]
MODELS = [("claude-sonnet-5-5", 0.6), ("claude-opus-5-5", 0.3), ("claude-haiku-5-5", 0.1)]
PII_TYPES = [("email", "medium"), ("phone", "medium"), ("aadhaar", "high"), ("pan", "medium"), ("card", "high"),
             ("secret", "high"), ("dob", "medium")]


def _git(cwd: Path, *args: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "seed", "GIT_AUTHOR_EMAIL": "seed@example.com",
           "GIT_COMMITTER_NAME": "seed", "GIT_COMMITTER_EMAIL": "seed@example.com"}
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def demo_line(path: str, i: int) -> str:
    """A realistic, non-trivial line of code (at least 10 alphanumerics), deterministic per file and index."""
    return f"    total_{i} = apply_rule(order, limit={i * 7 % 97}, mode=\"{Path(path).stem}\")"


def _make_repo(root: Path, remote: str, files: list[str], rnd: random.Random) -> None:
    if (root / ".git").exists():
        return
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "remote", "add", "origin", f"https://{remote}.git")
    for f in files:
        p = root / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(demo_line(f, i) + "\n" for i in range(rnd.randint(10, 80))) if not f.endswith(".csv")
                     else "id,name,email\n1,Test Person,test.person@example.com\n")
    s = root / ".seen"
    s.mkdir(parents=True)
    (s / ".gitignore").write_text(".cache/\n*.lock\n")
    (s / "policies.yaml").write_text(
        "- id: pol-auth\n  title: Security review on auth code\n  paths: [\"src/auth/**\"]\n  require_skill: security-review\n  mode: report\n"
        "- id: pol-phi\n  title: PHI redaction check on LLM code\n  paths: [\"llm/**\", \"src/llm/**\"]\n  require_skill: phi-redaction-check\n  mode: report\n")
    (s / "pii.yaml").write_text('allow_paths: ["tests/fixtures/**"]\nallow_values: ["*@example.com"]\ncustom_rules: []\n')
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")


def _attribute_first_file(db: Any, pid: str, root: Path, path: str, change_ids: list[str]) -> None:
    """Line prints for the first file of a project, as the capture hook would write them: every third line to the
    project's first change, the lines after those to its second, the rest left human. Same install key as production."""
    key = secret.key()
    n = len((root / path).read_text().splitlines())
    for i in range(n):
        if i % 3 < 2 and i % 3 < len(change_ids):
            db.add(LinePrint(project_id=pid, path=path, fp=fingerprint(demo_line(path, i), key), change_id=change_ids[i % 3]))


def seed(home: Path | None = None, days: int = 28, now: datetime | None = None) -> dict[str, int]:
    h = Path(home) if home else paths.home()
    if h.expanduser().resolve() == Path("~/.seen").expanduser().resolve():
        raise SystemExit("dev-seed refuses to write into ~/.seen. Set SEEN_HOME to a scratch folder.")
    os.environ["SEEN_HOME"] = str(h)
    paths.ensure_dir(h)
    rnd = random.Random(42)
    now = now or datetime.now(UTC).replace(microsecond=0)
    skill_hash = {sid: rnd.getrandbits(256).to_bytes(32, "big").hex() for sid, _, _ in SKILLS}
    counts = {"projects": 0, "sessions": 0, "changes": 0, "events": 0}
    lock: dict[str, Any] = {"approved": {}, "blocked": ["quick-sql-helper"]}
    for sid, kind, _ in SKILLS:
        if kind != "sideload" and sid not in ("quick-sql-helper", "release-notes"):
            lock["approved"][sid] = [("0000000" if sid == "tdd" else skill_hash[sid][:7])]  # tdd drifted after approval
    events: list[dict[str, Any]] = []
    with ledger_session() as db:
        if db.get(Project, "demo-payments") is not None:
            return counts  # already seeded
        for sid, kind, origin in SKILLS:
            first = _iso(now - timedelta(days=days + 5))
            db.add(Skill(id=sid, kind=kind, origin=origin, path=f"~/.claude/skills/{sid}" if kind == "user" else None,
                         description=f"{sid.replace('-', ' ').capitalize()} skill", first_seen=first, last_seen=_iso(now)))
            approved_now = kind != "sideload" and sid not in ("quick-sql-helper", "release-notes", "tdd")
            db.add(SkillVersion(skill_id=sid, hash=skill_hash[sid], first_seen=first,
                                approved_by="u_demo" if approved_now else None, approved_at=first if approved_now else None))
            if sid == "tdd":
                db.add(SkillVersion(skill_id=sid, hash="0000000" + "a" * 57, first_seen=_iso(now - timedelta(days=days + 20)),
                                    approved_by="u_demo", approved_at=_iso(now - timedelta(days=days + 19))))
        for pi, (name, remote, files) in enumerate(PROJECTS):
            pid = ["demo-payments", "demo-patient", "demo-pipes"][pi]
            root = h / "demo-repos" / name
            _make_repo(root, remote, files, rnd)
            (root / ".seen/skills.lock.json").write_text(json.dumps(lock, indent=2) + "\n")
            db.add(Project(id=pid, name=name, remote=remote, root_path=str(root), created_at=_iso(now - timedelta(days=days))))
            for pol, title, globs, req in (("pol-auth", "Security review on auth code", ["src/auth/**"], "security-review"),
                                           ("pol-phi", "PHI redaction check on LLM code", ["llm/**", "src/llm/**"], "phi-redaction-check")):
                db.add(Policy(id=f"{pid}:{pol}", project_id=pid, title=title, paths_json=json.dumps(globs), require_skill=req, mode="report"))
            counts["projects"] += 1
            pcids: list[str] = []
            for d in range(days, -1, -1):
                for _ in range(rnd.choice([0, 1, 1, 2, 3])):
                    start = now - timedelta(days=d, hours=rnd.randint(0, 9), minutes=rnd.randint(0, 59))
                    if start > now:
                        continue
                    sess_id = f"demo-{pid}-{rnd.getrandbits(48):012x}"
                    db.add(Session(id=sess_id, project_id=pid, started_at=_iso(start), ended_at=_iso(start + timedelta(minutes=40)),
                                   tool="claude-code", tool_version="2.1.302", user_id=rnd.choice(["u_demo", "u_alex", "u_sam"]),
                                   entrypoint="sdk-py" if int(sess_id[-1], 16) < 3 else "cli"))  # ~1 in 5: a plugin's background session
                    counts["sessions"] += 1
                    events.append({"type": "session.start", "occurred_at": _iso(start), "actor_kind": "system",
                                   "actor_id": "u_demo", "project_id": pid, "session_id": sess_id,
                                   "detail": {"plugin_version": "0.1.0", "lockfile_hash": "seed"}})
                    t = start
                    for seq in range(1, rnd.randint(1, 4) + 1):
                        t = t + timedelta(minutes=rnd.randint(2, 12))
                        cid = f"ch_{rnd.getrandbits(64):016x}"
                        model = rnd.choices([m for m, _ in MODELS], [w for _, w in MODELS])[0]
                        u = {"tok_in": rnd.randint(5, 400), "tok_out": rnd.randint(300, 9000), "tok_cache_read": rnd.randint(20_000, 400_000),
                             "tok_cache_write": rnd.randint(2000, 40_000)}
                        cost, pv = pricing.cost({model: {**u, "cw_5m": u["tok_cache_write"], "cw_1h": 0}})
                        touched = rnd.sample(files, rnd.randint(1, min(4, len(files))))
                        skills_run = rnd.sample([s for s, k, _ in SKILLS if k != "sideload"], rnd.randint(0, 2))
                        if rnd.random() < 0.03:
                            skills_run.append("sideloaded-helper")
                        pii = rnd.random() < 0.12 or (name == "patient360-web" and "data/patients.csv" in touched)
                        git_status = rnd.choices(["committed", "uncommitted", "reverted"], [0.75, 0.2, 0.05])[0]
                        db.add(Change(id=cid, project_id=pid, session_id=sess_id, seq=seq, started_at=_iso(t),
                                      ended_at=_iso(t + timedelta(minutes=3)), duration_s=rnd.randint(30, 600),
                                      prompt_text=None if rnd.random() < 0.3 else f"[seed] {rnd.choice(SUMMARIES).lower()}",
                                      summary=rnd.choice(SUMMARIES), model=model, **u, cost_usd=cost, price_version=pv,
                                      git_head_before=f"{rnd.getrandbits(160):040x}", git_head_after=f"{rnd.getrandbits(160):040x}",
                                      git_status=git_status,
                                      pii_state="found" if pii else "none", pii_count=0))
                        counts["changes"] += 1
                        pcids.append(cid)
                        events.append({"type": "turn.start", "occurred_at": _iso(t), "actor_kind": "user", "actor_id": "u_demo",
                                       "project_id": pid, "session_id": sess_id, "change_id": cid,
                                       "detail": {"prompt_hmac": secret.keyed(cid, 64), "prompt_len": rnd.randint(20, 400)}})
                        for f in touched:
                            a, r = rnd.randint(0, 120), rnd.randint(0, 40)
                            db.add(ChangeFile(change_id=cid, path=f, added=a, removed=r))
                            events.append({"type": "file.changed", "occurred_at": _iso(t), "actor_kind": "agent", "actor_id": "u_demo",
                                           "project_id": pid, "session_id": sess_id, "change_id": cid, "subject": f,
                                           "detail": {"path": f, "added": a, "removed": r}})
                        for o, s in enumerate(skills_run, 1):
                            status = "blocked" if s == "quick-sql-helper" else "changed" if s == "tdd" else \
                                "unreviewed" if s in ("release-notes", "sideloaded-helper") else "approved"
                            db.add(SkillInvocation(change_id=cid, ordinal=o, skill_id=s, hash=skill_hash[s],
                                                   trigger=rnd.choice(["model", "model", "user", "subagent"]), status=status))
                            events.append({"type": "skill.invoked", "occurred_at": _iso(t), "actor_kind": "agent", "actor_id": "u_demo",
                                           "project_id": pid, "session_id": sess_id, "change_id": cid, "subject": s,
                                           "detail": {"skill": s, "hash": skill_hash[s][:12], "status": status}})
                        for pol, prefixes, req in (("pol-auth", ("src/auth/",), "security-review"),
                                                ("pol-phi", ("llm/", "src/llm/"), "phi-redaction-check")):
                            if any(f.startswith(prefixes) for f in touched):
                                met = int(req in skills_run or rnd.random() < 0.7)
                                db.add(PolicyResult(change_id=cid, policy_id=f"{pid}:{pol}", met=met))
                                events.append({"type": "policy.result", "occurred_at": _iso(t), "actor_kind": "system", "actor_id": "u_demo",
                                               "project_id": pid, "session_id": sess_id, "change_id": cid, "subject": pol,
                                               "outcome": "ok" if met else "failed", "detail": {"policy": pol, "met": bool(met)}})
                        if pii:
                            total = 0
                            for typ, conf in rnd.sample(PII_TYPES, rnd.randint(1, 2)):
                                src = rnd.choice([("file_read", "Read data/patients.csv", "model"), ("prompt", "Prompt", "model"),
                                                  ("tool_output", "Bash output", "model"), ("mcp", "MCP crm.lookup_customer", "model"),
                                                  ("diff_added", f"Write {touched[0]}", "repo")])
                                if name == "patient360-web" and rnd.random() < 0.6:
                                    src = ("file_read", "Read data/patients.csv", "model")
                                n = rnd.randint(1, 30)
                                total += n
                                fid = f"pf_{rnd.getrandbits(64):016x}"
                                db.add(PiiFinding(id=fid, change_id=cid, type=typ, confidence=conf, count=n, distinct_count=max(1, n // 2),
                                                  source_kind=src[0], source_ref=src[1], destination=src[2], detector="regex",
                                                  status="test_data" if rnd.random() < 0.1 else "open",
                                                  fingerprints_json=json.dumps([secret.keyed(f"seed-{typ}-{k}") for k in range(min(3, n))])))
                                events.append({"type": "pii.finding", "occurred_at": _iso(t), "actor_kind": "hook", "actor_id": "u_demo",
                                               "project_id": pid, "session_id": sess_id, "change_id": cid, "subject": typ,
                                               "detail": {"finding": fid, "type": typ, "count": n, "confidence": conf, "destination": src[2]}})
                            db.query(Change).filter(Change.id == cid).update({"pii_count": total})
                        events.append({"type": "turn.end", "occurred_at": _iso(t + timedelta(minutes=3)), "actor_kind": "agent",
                                       "actor_id": "u_demo", "project_id": pid, "session_id": sess_id, "change_id": cid,
                                       "detail": {"tok_out": u["tok_out"], "cost_usd": cost, "files": len(touched)}})
                    events.append({"type": "session.end", "occurred_at": _iso(t + timedelta(minutes=5)), "actor_kind": "system",
                                   "actor_id": "u_demo", "project_id": pid, "session_id": sess_id, "detail": {"reason": "other"}})
            _attribute_first_file(db, pid, root, files[0], pcids)
        db.commit()
    events.sort(key=lambda e: e["occurred_at"])
    events.insert(5, {"type": "approval.skill", "occurred_at": events[5]["occurred_at"], "actor_kind": "user", "actor_id": "u_demo",
                      "project_id": "demo-payments", "subject": "security-review",
                      "detail": {"skill": "security-review", "old": "unreviewed", "new": "approved"}})
    for i in range(0, len(events), 2000):
        audit.append(events[i:i + 2000])
    audit.record_head()
    counts["events"] = len(events)
    return counts
