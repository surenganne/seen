"""`seen` command line."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer
from sqlalchemy import select

from seen_core import audit, brand, config, gitutil, ingest, paths, safeio
from seen_core.db import ledger_session
from seen_core.db.models import Change, ChangeFile, Project, Session, SkillInvocation
from seen_core.headline import clean
from seen_core.identity import user_id
from seen_core.project import resolve_project
from seen_core.provenance.blame import blame_file, is_failure
from seen_core.provenance.enrich import enrich_blocks
from seen_core.provenance.report import FAIL_ON, Report, build_report, gate, render_md

app = typer.Typer(help=f"{brand.NAME}: {brand.TAGLINE}", no_args_is_help=True, add_completion=False)
skills_app = typer.Typer(help="Skill inventory and approvals", no_args_is_help=True)
app.add_typer(skills_app, name="skills")

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


_LIMIT = ("agent / human / not observed are shown separately. Not observed means Seen could not have seen who wrote the line "
          "(before Seen, or a gap in capture); it is not a claim that a person wrote it. Checked: git blame, fingerprints of "
          "recorded edits.")


def _ist(ts: str | None) -> str:
    try:
        return (datetime.fromisoformat((ts or "").replace("Z", "+00:00")) + timedelta(minutes=330)).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return "-"


@app.command("blame")
def blame_cmd(path: str = typer.Argument(..., help="File, relative to the repo root"),
              rev: str = typer.Option("HEAD", "--rev", help="Commit to blame"),
              as_json: bool = typer.Option(False, "--json", help="Machine-readable output (no line text)")) -> None:
    """Who wrote each line: the agent, a person, or not observed."""
    pid, _ = _project_or_exit()

    def fail(msg: str) -> typer.Exit:
        typer.echo(msg, err=True)
        return typer.Exit(2)

    with ledger_session() as db:
        proj = db.get(Project, pid)
        if proj is None:
            raise fail("This repository has no recorded changes yet.")
        try:
            fp = blame_file(db, proj, path, rev)
        except ValueError as e:
            raise fail(f"Cannot blame {clean(path)!r}: {clean(str(e))}.") from e
        if is_failure(fp.reason):
            raise fail(f"Cannot blame {clean(path)!r} at {clean(rev)}: {clean(fp.reason)}.")
        blocks = enrich_blocks(db, fp.blocks)
    if as_json:
        typer.echo(json.dumps({**dataclasses.asdict(fp), "blocks": [dataclasses.asdict(b) for b in blocks]}, indent=2))
        return
    if path.endswith(".ipynb"):
        typer.echo("Notebook files are not line-attributed (a cell is one JSON line); showing blame counts only.")
    if fp.truncated:
        typer.echo("Stopped at the time budget; the result is incomplete.")
    for b in blocks:
        typer.echo(f"{b.start}-{b.end}  {b.who}  {clean(b.headline) or '-'}  {_ist(b.started_at)} IST  {clean(b.model) or '-'}")
    c = fp.counts
    if fp.reason:
        typer.echo(f"No lines attributed: {clean(fp.reason)}.")
        return
    typer.echo(f"{fp.path} at {rev}: agent {c['agent']} / human {c['human']} / not observed {c['not_observed']} lines"
               f" ({c['neutral']} blank or punctuation-only). {_LIMIT}")


_FAIL_HELP = f"Exit 1 when it holds: {', '.join(FAIL_ON)} (repeatable)"


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _post(root: Path, pid: str, rep: Report, body: str, yes: bool, fail: Callable[[str], typer.Exit]) -> None:
    if not yes:
        try:
            if not typer.confirm("Post this to the PR?", default=False):
                return
        except typer.Abort:  # EOF or Ctrl-C: no answer is a no
            typer.echo("")
            return
    try:  # fixed argv, no shell; the body goes on stdin, never into the command line
        r = subprocess.run(["gh", "pr", "comment", "--body-file", "-"], input=body, text=True, capture_output=True,
                           timeout=30, cwd=root)
    except FileNotFoundError as e:
        raise fail("gh not found; install the GitHub CLI: https://cli.github.com") from e
    except (OSError, subprocess.TimeoutExpired) as e:
        raise fail(f"gh did not run: {type(e).__name__}.") from e
    if r.returncode:
        first = (r.stderr or "").strip().splitlines()[:1]
        raise fail(f"gh failed (exit {r.returncode}): {clean(first[0]) if first else 'no message'}")
    # counts only: no headlines, branch or repo names, URLs or comment text
    audit.append([{"type": "provenance.reported", "actor_kind": "user", "actor_id": user_id(), "project_id": pid,
                   "detail": {"added": sum(rep.added.values()) + rep.neutral, "requests": len(rep.requests)}}])
    typer.echo("Posted the report to the PR.")


@app.command("pr-report")
def pr_report_cmd(base: str = typer.Option(..., "--base", help="Base ref (the range is BASE...HEAD, from the merge base)"),
                  head: str = typer.Option("HEAD", "--head", help="Head ref"),
                  fmt: str = typer.Option("md", "--format", help="md or json"),
                  no_cost: bool = typer.Option(False, "--no-cost", help="Leave the API-equivalent cost out"),
                  fail_on: list[str] = typer.Option([], "--fail-on", help=_FAIL_HELP),
                  post: bool = typer.Option(False, "--post", help="Post the Markdown as a comment on this branch's PR (uses gh)"),
                  yes: bool = typer.Option(False, "--yes", help="With --post: do not ask first")
                  ) -> None:
    """Who wrote the lines a branch adds, for a pull request."""
    def fail(msg: str) -> typer.Exit:
        typer.echo(msg, err=True)
        return typer.Exit(2)

    if fmt not in ("md", "json"):
        raise fail("--format must be md or json.")
    if bad := [x for x in fail_on if x not in FAIL_ON]:
        raise fail(f"Unknown --fail-on {clean(bad[0])!r}; use one of {', '.join(FAIL_ON)}.")
    if post and fmt != "md":
        raise fail("--post posts the Markdown report only; drop --format json.")
    if post and not yes and not _stdin_is_tty():
        raise fail("--post needs a terminal to ask first; pass --yes to post without asking.")
    pid, root = _project_or_exit()
    if post:
        # gh comments on the PR of the checked-out branch: the report must describe exactly that commit
        h = gitutil.run(root, "rev-parse", "--verify", "--end-of-options", f"{head}^{{commit}}")
        if not h or h != gitutil.run(root, "rev-parse", "--verify", "HEAD"):
            raise fail("--post only works when --head is the checked-out branch's HEAD; check it out first.")
    with ledger_session() as db:
        proj = db.get(Project, pid)
        if proj is None:
            raise fail("This repository has no recorded changes yet.")
        try:
            rep = build_report(db, proj, base, head, with_cost=not no_cost)
        except ValueError as e:
            raise fail(f"Cannot report {clean(base)!r}...{clean(head)!r}: {clean(str(e))}.") from e
    body = json.dumps(dataclasses.asdict(rep), indent=2) if fmt == "json" else render_md(rep)
    typer.echo(body, nl=fmt == "json")
    if post:
        _post(root, pid, rep, body, yes, fail)
    if reasons := gate(rep, set(fail_on)):
        for x in reasons:
            typer.echo(x, err=True)
        raise typer.Exit(1)


@app.command()
def init() -> None:
    """Set up .seen/ in this repo."""
    pid, root = _project_or_exit()
    s = root / ".seen"
    created = []
    for name, text in ((".gitignore", ".cache/\n*.lock\n"), ("policies.yaml", POLICIES_TEMPLATE), ("pii.yaml", PII_TEMPLATE),
                       ("skills.lock.json", json.dumps({"approved": {}, "blocked": []}, indent=2) + "\n")):
        if not (s / name).exists():
            safeio.write_text(s / name, text, root)
            created.append(name)
    audit.append([{"type": "config.changed", "actor_kind": "user", "actor_id": user_id(), "project_id": pid,
                   "subject": "project.init", "detail": {"key": "project.init", "old": None,
                                                         "new": {"created": created}}}])
    typer.echo(f"Initialised {s} ({', '.join(created) or 'already present'}).")


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
    typer.echo("Audit: " + (f"chain verified, {v.count} events, head {v.head[:12]}" if v.ok
                            else f"CHAIN BROKEN at seq {v.break_seq} ({v.reason})"))


@app.command("import")
def import_cmd(dry_run: bool = typer.Option(False, "--dry-run", help="Count what would be imported, write nothing")) -> None:
    """Record this repo's past Claude Code sessions from their transcripts (sessions already recorded are skipped)."""
    from seen_core import backfill

    _project_or_exit()
    r = backfill.import_project(Path.cwd(), dry_run=dry_run)
    verb = "Would import" if dry_run else "Imported"
    typer.echo(f"{verb} {r.sessions} sessions, {r.changes} changes, API-equivalent cost ≈ ${r.cost_usd:.2f}; "
               f"{r.skipped} already recorded.")
    if r.sessions and not dry_run:
        typer.echo("Imported sessions have no git status; line counts come from edit inputs.")


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
    line(bool(hook), f"seen-hook on PATH: {hook or 'not found (uv tool install git+https://github.com/surenganne/seen#subdirectory=packages/cli)'}")
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
         "not installed (claude plugin marketplace add surenganne/seen; claude plugin install seen@seen-tools)"))
    from seen_core import upgrade

    skews = upgrade.skew()
    for m in skews:
        line(False, m)
    if not skews:
        line(True, f"versions in step: cli {brand.VERSION}, plugin {upgrade.plugin_version() or 'not installed'}")
    latest = upgrade.latest_release()
    if upgrade.is_newer(latest, brand.VERSION):
        line(False, f"update available: {latest} (you have {brand.VERSION}): run `seen upgrade`")
    try:
        with ledger_session() as db:
            db.execute(select(Change.id).limit(1))
            from sqlalchemy import func as sqlfunc

            from seen_core.db.models import Outbox

            parked = db.execute(select(sqlfunc.count(Outbox.id), sqlfunc.max(Outbox.last_status))
                                .where(Outbox.dead_at.is_not(None), Outbox.sent_at.is_(None))).one()
        line(True, f"ledger {paths.ledger_db()} migrated")
        if parked[0]:
            line(False, f"sync: {parked[0]} batch(es) rejected by the server (last status {parked[1]}): "
                        "fix the key or server, then run `seen sync --retry-failed`")
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


@app.command("version")
def version_cmd() -> None:
    """Versions of every installed piece and the ledger schema."""
    from importlib import metadata

    from seen_core import upgrade

    hook = shutil.which("seen-hook")
    rows = [("seen-cli", metadata.version("seen-cli")), ("seen_core", brand.VERSION),
            ("plugin", upgrade.plugin_version() or "not installed"),
            ("seen-hook", f"{upgrade.hook_version(hook) or 'unknown'} ({hook or 'not on PATH'})"),
            ("ledger schema", f"{upgrade.ledger_revision() or 'none yet'} (this CLI: {upgrade.schema_head()})"),
            ("installed from", upgrade.install_source())]
    for k, v in rows:
        typer.echo(f"{k:<15} {v}")


@app.command("upgrade")
def upgrade_cmd(yes: bool = typer.Option(False, "--yes", help="Run the upgrade. Without this, only report the plan"),
                check: bool = typer.Option(False, "--check", help="Report only (the default; kept for scripts and the plugin command)"),
                source: str = typer.Option(None, help="Reinstall from this folder or git URL (default: where it was installed from)")) -> None:
    """Upgrade the CLI and the plugin together. Reports first; `--yes` runs it."""
    from seen_core import upgrade

    latest = upgrade.latest_release()
    typer.echo(f"current {brand.VERSION}; latest release " + (latest or "unknown (offline, no release tags, or SEEN_NO_UPDATE_CHECK set)"))
    for m in upgrade.skew():
        typer.echo(f"  !!  {m}")
    try:
        cmds = upgrade.plan(source or upgrade.install_source(), have_claude=bool(shutil.which("claude")))
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from None
    if not shutil.which("claude"):
        typer.echo("`claude` not on PATH: afterwards run `claude plugin marketplace update seen-tools` and "
                   "`claude plugin update seen@seen-tools` yourself.")
    if check or not yes:
        typer.echo("Would run (add --yes):")
        for c in cmds:
            typer.echo("  $ " + " ".join(c))
        return
    ok, why = upgrade.healthy()
    if not ok:
        typer.echo(f"Refusing to upgrade: {why}. Fix it first (`seen doctor`).")
        raise typer.Exit(1)
    for c in cmds:
        typer.echo("  $ " + " ".join(c))
    results = upgrade.run(cmds)
    if len(results) < len(cmds) or any(rc for _c, rc in results):
        typer.echo("Upgrade stopped at a failed step; nothing after it ran. Re-run, or run the steps above by hand.")
        raise typer.Exit(1)
    typer.echo("Upgraded. To load the new plugin version, restart Claude Code, then run `seen doctor`.")


@app.command("purge")
def purge_cmd(before: str = typer.Option(None, help="Erase changes and sessions started before this date (YYYY-MM-DD)"),
              project: str = typer.Option(None, help="Erase everything recorded for one project id"),
              everything: bool = typer.Option(False, "--all", help="Erase the whole ledger"),
              yes: bool = typer.Option(False, "--yes", help="Do it. Without this, only report what would be erased")) -> None:
    """Erase ledger data (DPDP retention/erasure). The audit trail is kept and records the purge (counts only)."""
    from seen_core import purge

    if not (before or project or everything):
        typer.echo("Give --before, --project or --all.", err=True)
        raise typer.Exit(2)
    res = purge.purge(before=before, project=project, everything=everything, actor=user_id(), dry_run=not yes)
    typer.echo(("Erased: " if yes else "Would erase (add --yes): ") + ", ".join(f"{v} {k}" for k, v in res.items()))
    if yes:
        typer.echo("Run `seen docker-sync` to refresh the Docker dashboard copy; older snapshots still hold the data until pruned.")


@app.command("docker-sync")
def docker_sync(dest: Path = typer.Option(Path("~/.seen-docker"), help="Snapshot folder mounted into the dashboard container"),
                watch: int = typer.Option(0, help="Repeat every N seconds (0 = once)"),
                restart: bool = typer.Option(False, help="Restart the dashboard container after each snapshot so it opens the new copy")) -> None:
    """Snapshot ~/.seen for the Docker dashboard. The container never opens the live ledger."""
    import subprocess
    import time

    from seen_core import snapshot

    while True:
        try:
            snap = snapshot.snapshot(paths.home(), dest.expanduser())
        except SystemExit as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(2) from None
        typer.echo(f"Snapshot {snap}")
        if restart:
            subprocess.run(["docker", "compose", "restart", "dashboard"], check=False)
        if not watch:
            return
        time.sleep(watch)


@app.command("dev-seed")
def dev_seed(home: Path = typer.Option(None, help="Scratch SEEN_HOME to fill (default: $SEEN_HOME)")) -> None:
    """Fill a scratch SEEN_HOME with generated data. Never touches ~/.seen."""
    from seen_core import devseed

    target = home or (Path(os.environ["SEEN_HOME"]) if os.environ.get("SEEN_HOME") else None)
    if target is None:
        typer.echo("Give --home or set SEEN_HOME to a scratch folder.", err=True)
        raise typer.Exit(2)
    try:
        counts = devseed.seed(target)
    except SystemExit as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from None
    typer.echo(f"Seeded {target}: " + ", ".join(f"{v} {k}" for k, v in counts.items()))


@app.command()
def serve(port: int = typer.Option(47821, help="Port (default 47821, off the common defaults)"),
          host: str = typer.Option("127.0.0.1", help="Bind address; keep 127.0.0.1 outside containers"),
          open_browser: bool = typer.Option(False, "--open", help="Open the dashboard in a browser"),
          allow_remote: bool = typer.Option(False, "--allow-remote",
                                            help="Allow a non-loopback bind (containers only; publish the port on 127.0.0.1)")) -> None:
    """Run the local dashboard."""
    import uvicorn

    if host not in ("127.0.0.1", "localhost", "::1") and not allow_remote:
        typer.echo(f"Refusing to bind {host}: the local API has no login. Use --allow-remote only inside a container.", err=True)
        raise typer.Exit(2)

    from seen_local.app import create_app, default_web_dist

    dist = default_web_dist()
    if dist is None:
        typer.echo("Web build not found: API only (build it with `npm run build` in web/).", err=True)
    if open_browser:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    uvicorn.run(create_app(dist), host=host, port=port, log_level="warning", server_header=False)


audit_app = typer.Typer(help="Tamper-evident audit trail", no_args_is_help=True)
app.add_typer(audit_app, name="audit")


@audit_app.command("verify")
def audit_verify() -> None:
    """Recompute the hash chain and print the first break."""
    v = audit.verify()
    if v.ok:
        typer.echo(f"Chain verified: {v.count} events, head {v.head} (seq {v.head_seq}). Not anchored off this machine.")
        return
    typer.echo(f"BROKEN at seq {v.break_seq}: {v.reason}\n  expected {v.expected}\n  found    {v.found}")
    raise typer.Exit(1)


@audit_app.command("export")
def audit_export(project: str = typer.Option(None, help="Project id (default: all)"),
                 date_from: str = typer.Option(None, "--from", help="YYYY-MM-DD"),
                 date_to: str = typer.Option(None, "--to", help="YYYY-MM-DD"),
                 fmt: str = typer.Option("ndjson", "--format", help="csv | ndjson"),
                 out: Path = typer.Option(None, help="Output path without extension")) -> None:
    """Write events plus a manifest (range, count, head hash, verification result)."""
    from seen_core import export

    if fmt not in ("csv", "ndjson"):
        raise typer.BadParameter("format must be csv or ndjson")
    base = out or paths.home() / "exports" / f"audit-{project or 'all'}"
    path = export.export(base, project=project, date_from=date_from, date_to=date_to, fmt=fmt, actor=user_id())
    m = json.loads(path.with_suffix(".manifest.json").read_text())
    typer.echo(f"{m['count']} events -> {path} (verified: {m['verification']['ok']}, head {m['head_hash'][:12]})")


@app.command("sync")
def sync_cmd(retry_failed: bool = typer.Option(False, "--retry-failed", help="Send batches the server rejected earlier (after fixing the key or server)")) -> None:
    """Send unsynced metadata to the team server (only the fields switched on in [sync])."""
    from seen_core import sync

    if not config.load()["sync"]["enabled"]:
        typer.echo("Team sync is off. Turn it on in Settings or [sync] enabled = true.")
        return
    try:
        r = sync.push(retry_dead=retry_failed)
    except sync.SyncError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from None
    a = sync.anchor()
    typer.echo(f"sent {r['sent']} batch(es), {r['failed']} failed (will retry with backoff)"
               + (f", {r['dead']} rejected by the server (parked; fix the key or server, then `seen sync --retry-failed`)" if r["dead"] else "")
               + (f"; audit anchored through seq {a['seq']}" if a else ""))


if __name__ == "__main__":
    app()
