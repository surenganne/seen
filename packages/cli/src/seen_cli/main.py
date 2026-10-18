"""`seen` command line."""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer
from sqlalchemy import select

from seen_core import audit, brand, config, ingest, paths
from seen_core.db import ledger_session
from seen_core.db.models import Change, ChangeFile, Project, Session, Skill, SkillInvocation
from seen_core.identity import user_id
from seen_core.project import resolve_project

app = typer.Typer(help=f"{brand.NAME}: {brand.TAGLINE}", no_args_is_help=True, add_completion=False)
skills_app = typer.Typer(help="Skill inventory and approvals", no_args_is_help=True)
app.add_typer(skills_app, name="skills")

MEMORY_RULES = ["Write(.seen/memory/**)", "Edit(.seen/memory/**)"]

POLICIES_TEMPLATE = """# Required-skill rules. Each rule: when a change touches `paths`, `require_skill` must run.
# mode: report (record only) | enforce (block Stop once until the skill runs)
# - id: pol-example
#   title: Security review on auth code
#   paths: ["src/auth/**"]
#   require_skill: security-review
#   mode: report
[]
"""

PII_TEMPLATE = """# Project PII allowlist and custom rules (reviewed in PRs).
allow_paths: ["tests/fixtures/**"]
allow_values: ["*@example.com", "*@example.org", "*@test.local"]
custom_rules: []
"""


def _project_or_exit(cwd: Path | None = None) -> tuple[str, Path]:
    p = resolve_project(cwd or Path.cwd())
    if p is None:
        typer.echo("Not inside a git repository.", err=True)
        raise typer.Exit(1)
    return p.id, Path(p.root)


@app.command()
def init() -> None:
    """Set up .seen/ in this repo and allow memory writes without prompts."""
    pid, root = _project_or_exit()
    s = root / ".seen"
    (s / "memory").mkdir(parents=True, exist_ok=True)
    created = []
    for name, text in ((".gitignore", ".cache/\n"), ("policies.yaml", POLICIES_TEMPLATE), ("pii.yaml", PII_TEMPLATE),
                       ("skills.lock.json", json.dumps({"approved": {}, "blocked": []}, indent=2) + "\n")):
        if not (s / name).exists():
            (s / name).write_text(text)
            created.append(name)
    sf = root / ".claude" / "settings.json"
    settings = json.loads(sf.read_text()) if sf.exists() else {}
    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    added = [r for r in MEMORY_RULES if r not in allow]
    allow.extend(added)
    if added:
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(json.dumps(settings, indent=2) + "\n")
    audit.append([{"type": "config.changed", "actor_kind": "user", "actor_id": user_id(), "project_id": pid,
                   "subject": "project.init", "detail": {"key": "project.init", "old": None,
                                                         "new": {"created": created, "allow_rules_added": len(added)}}}])
    typer.echo(f"Initialised {s} ({', '.join(created) or 'already present'}); memory allow rules: {len(added)} added.")


def _changes(pid: str | None, days: int) -> list[Change]:
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with ledger_session() as db:
        q = select(Change).where(Change.started_at >= since).order_by(Change.started_at)
        if pid:
            q = q.where(Change.project_id == pid)
        return list(db.scalars(q))


@app.command()
def report(project: str = typer.Option(None, help="Project id (default: this repo)"),
           days: int = typer.Option(7, help="How many days back")) -> None:
    """What the agents changed, what it cost, and which skills ran."""
    pid = project or _project_or_exit()[0]
    rows = _changes(pid, days)
    if not rows:
        typer.echo(f"No changes in the last {days} days.")
        return
    total_cost = 0.0
    with ledger_session() as db:
        for c in rows:
            files = list(db.scalars(select(ChangeFile).where(ChangeFile.change_id == c.id)))
            skills = [i.skill_id for i in db.scalars(select(SkillInvocation).where(SkillInvocation.change_id == c.id)
                                                     .order_by(SkillInvocation.ordinal))]
            total_cost += c.cost_usd or 0
            typer.echo(f"{(c.started_at or '')[:16]}  #{c.seq}  {c.summary or '(no summary)'}")
            typer.echo(f"    tokens in/out/cache r/w: {c.tok_in}/{c.tok_out}/{c.tok_cache_read}/{c.tok_cache_write}"
                       f"  cost≈${(c.cost_usd or 0):.4f} ({c.price_version})  git: {c.git_status or '-'}")
            for f in files:
                typer.echo(f"    {f.path}  +{f.added} -{f.removed}")
            if skills:
                typer.echo(f"    skills: {', '.join(skills)}")
    typer.echo(f"{len(rows)} changes, API-equivalent cost ≈ ${total_cost:.4f} (prices unverified until confirmed)")


@app.command()
def status() -> None:
    """This repo's ledger at a glance."""
    pid, root = _project_or_exit()
    with ledger_session() as db:
        proj = db.get(Project, pid)
        n = len(list(db.scalars(select(Change.id).where(Change.project_id == pid))))
        last = db.scalars(select(Session).where(Session.project_id == pid).order_by(Session.started_at.desc())).first()
    v = audit.verify()
    typer.echo(f"Project: {proj.name if proj else root.name} ({pid})")
    typer.echo(f"Changes recorded: {n}")
    typer.echo(f"Last session: {last.started_at if last else 'none'}")
    typer.echo(f"Memory folder: {'present' if (root / '.seen/memory').is_dir() else 'missing (run seen init)'}")
    typer.echo("Audit: " + (f"chain verified, {v.count} events, head {v.head[:12]}" if v.ok
                            else f"CHAIN BROKEN at seq {v.break_seq} ({v.reason})"))


@app.command("ingest")
def ingest_cmd(session: str = typer.Option(..., help="Session id to (re)ingest")) -> None:
    """Re-run ingest for a session's current turn (idempotent)."""
    r = ingest.finish_turn(session)
    typer.echo(r.get("change_id") or "nothing to ingest")


@skills_app.command("scan")
def skills_scan() -> None:
    """Scan installed skills and record their versions."""
    from seen_core.skills.scan import write_inventory

    p = resolve_project(Path.cwd())
    write_inventory(p.root if p else None, p.id if p else None)
    with ledger_session() as db:
        ingest._sync_inventory(db, p.id if p else None)
        db.commit()
    typer.echo(f"{len(ingest.inventory(p.id if p else None))} skills scanned")


@skills_app.command("list")
def skills_list() -> None:
    """Installed skills with kind and current hash."""
    p = resolve_project(Path.cwd())
    inv = ingest.inventory(p.id if p else None)
    if not inv:
        typer.echo("No inventory yet: run `seen skills scan`.")
        return
    from seen_core.skills import lock

    lk = lock.load(Path(p.root)) if p else lock.Lockfile()
    for s in inv:
        typer.echo(f"{s['id']:<50} {s['kind']:<8} {s['hash'][:7]}  {lock.status(lk, s['id'], s['hash'])}")


@app.command()
def doctor() -> None:
    """Check Python, hooks, plugin install, databases and PATH."""
    ok = True

    def line(good: bool, msg: str) -> None:
        nonlocal ok
        ok &= good
        typer.echo(("  ok  " if good else "  !!  ") + msg)

    line(sys.version_info >= (3, 11), f"python {sys.version.split()[0]} (need 3.11+)")
    hook = shutil.which("seen-hook")
    line(bool(hook), f"seen-hook on PATH: {hook or 'not found (uv tool install seen-cli)'}")
    seens = [str(Path(d) / "seen") for d in os.environ.get("PATH", "").split(os.pathsep) if (Path(d) / "seen").is_file()]
    me = shutil.which("seen")
    mine = str(Path(sys.argv[0]).resolve()) if sys.argv and sys.argv[0] else ""
    shadow = [s for s in seens if Path(s).resolve() != Path(mine)]
    line(not shadow or (me is not None and Path(me).resolve() == Path(mine)),
         "PATH: " + (f"another 'seen' executable comes first: {shadow[0]}" if shadow else "no conflicting 'seen' executable"))
    from seen_core.skills.scan import claude_dir

    inst = claude_dir() / "plugins" / "installed_plugins.json"
    has = inst.exists() and f"{brand.PLUGIN}@{brand.MARKETPLACE}" in inst.read_text()
    line(has, f"plugin {brand.PLUGIN}@{brand.MARKETPLACE} " + ("installed" if has else
         "not installed (claude plugin marketplace add <repo>; claude plugin install seen@seen-tools)"))
    try:
        with ledger_session() as db:
            db.execute(select(Change.id).limit(1))
        line(True, f"ledger {paths.ledger_db()} migrated")
    except Exception as e:  # doctor reports, never crashes
        line(False, f"ledger: {type(e).__name__}")
    v = audit.verify()
    line(v.ok, f"audit chain: {v.count} events " + ("verified" if v.ok else f"BROKEN at seq {v.break_seq}"))
    try:
        config.load()
        line(True, f"config {paths.config_toml()} readable")
    except Exception as e:
        line(False, f"config: {type(e).__name__}")
    log = paths.hook_log()
    errors = log.read_text().count("Traceback") if log.exists() else 0
    line(errors == 0, f"hook log: {errors} errors in {log}")
    raise typer.Exit(0 if ok else 0)  # doctor is advisory; exit 0 so scripts can read the report
