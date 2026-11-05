import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seen_cli.main import app
from seen_core import audit
from tests.core.test_skills import mkskill
from tests.helpers import Replay

cli = CliRunner()


def invoke(*args: str, cwd: Path | None = None) -> str:
    old = os.getcwd()
    try:
        if cwd:
            os.chdir(cwd)
        r = cli.invoke(app, list(args), catch_exceptions=False)
    finally:
        os.chdir(old)
    assert r.exit_code == 0, r.output
    return r.output


def recorded(repo: Path, tmp_path: Path) -> None:
    r = Replay(repo, tmp_path)
    r.start()
    r.prompt()
    (repo / "a.py").write_text("one\ntwo\nthree\n")
    r.model_works()
    r.stop()


def test_init_scaffolds_repo_and_is_idempotent(repo: Path) -> None:
    invoke("init", cwd=repo)
    s = repo / ".seen"
    assert (s / "policies.yaml").exists() and (s / "pii.yaml").exists()
    assert json.loads((s / "skills.lock.json").read_text()) == {"approved": {}, "blocked": []}
    assert ".cache/" in (s / ".gitignore").read_text()
    assert not (s / "memory").exists() and not (repo / ".claude/settings.json").exists()  # init writes nothing outside .seen/
    (s / "pii.yaml").write_text("# edited\n")
    invoke("init", cwd=repo)
    assert (s / "pii.yaml").read_text() == "# edited\n"
    assert audit.query(type_="config.changed")


def test_report_prints_last_week(repo: Path, tmp_path: Path) -> None:
    recorded(repo, tmp_path)
    out = invoke("report", "--days", "7", cwd=repo)
    assert "greeted" in out and "a.py" in out and "733" in out


def test_report_by_project_id(repo: Path, tmp_path: Path) -> None:
    recorded(repo, tmp_path)
    from seen_core.project import resolve_project

    pid = resolve_project(repo).id  # type: ignore[union-attr]
    assert "greeted" in invoke("report", "--project", pid)


def test_status(repo: Path, tmp_path: Path) -> None:
    recorded(repo, tmp_path)
    out = invoke("status", cwd=repo)
    assert "changes" in out.lower() and "chain verified" in out.lower()


def test_skills_scan_and_list(repo: Path) -> None:
    mkskill(repo / ".claude/skills", "greet-skill")
    assert "1" in invoke("skills", "scan", cwd=repo)
    out = invoke("skills", "list", cwd=repo)
    assert "greet-skill" in out and "project" in out


def test_doctor_reports_checks(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "seen").write_text("#!/bin/sh\n")
    (fake / "seen").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    out = invoke("doctor", cwd=repo)
    for word in ("python", "ledger", "audit", "plugin", "PATH"):
        assert word.lower() in out.lower()
    assert "another 'seen'" in out.lower()


def test_ingest_command_replays_session(repo: Path, tmp_path: Path) -> None:
    recorded(repo, tmp_path)
    assert "ch_" in invoke("ingest", "--session", "sess-1")


def test_dev_seed_into_explicit_home(tmp_path: Path) -> None:
    home = tmp_path / "dev"
    out = invoke("dev-seed", "--home", str(home))
    assert "changes" in out and (home / "ledger.db").exists() and (home / "demo-repos/payments-api/.seen/policies.yaml").is_file()


def test_dev_seed_refuses_real_home(monkeypatch: pytest.MonkeyPatch) -> None:
    real = Path("~/.seen").expanduser() / "ledger.db"
    before = real.stat().st_mtime_ns if real.exists() else None  # a real install may already have a ledger
    r = cli.invoke(app, ["dev-seed", "--home", str(real.parent)])
    assert r.exit_code != 0 and (real.stat().st_mtime_ns if real.exists() else None) == before


def test_serve_starts_and_answers(tmp_path: Path) -> None:
    import socket
    import subprocess
    import sys
    import time
    import urllib.request

    home = tmp_path / "dev"
    invoke("dev-seed", "--home", str(home))
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    p = subprocess.Popen([sys.executable, "-m", "seen_cli.main", "serve", "--port", str(port)],
                         env={**os.environ, "SEEN_HOME": str(home)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                body = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/projects", timeout=1).read()
                break
            except OSError:
                time.sleep(0.2)
        assert b"payments-api" in body
    finally:
        p.terminate()
        p.wait(5)


def test_serve_turns_the_access_log_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """The OIDC callback carries a code and state in its query: uvicorn's access log must not record them."""
    import uvicorn

    kw: dict = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **k: kw.update(k))
    assert cli.invoke(app, ["serve"]).exit_code == 0
    assert kw["access_log"] is False


def test_serve_refuses_non_loopback_without_flag() -> None:
    r = cli.invoke(app, ["serve", "--host", "0.0.0.0"])
    assert r.exit_code == 2 and "--allow-remote" in r.output


def test_audit_verify_and_export_cli(repo: Path, tmp_path: Path) -> None:
    recorded(repo, tmp_path)
    assert "verified" in invoke("audit", "verify").lower()
    out = invoke("audit", "export", "--format", "csv", "--out", str(tmp_path / "exp"))
    assert (tmp_path / "exp.csv").exists() and (tmp_path / "exp.manifest.json").exists() and "events" in out


def test_audit_verify_reports_break(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    import sqlite3

    recorded(repo, tmp_path)
    c = sqlite3.connect(seen_home / "audit.db", isolation_level=None)
    c.execute("DROP TRIGGER audit_no_update")
    c.execute("UPDATE audit_events SET outcome='x' WHERE seq=2")
    r = cli.invoke(app, ["audit", "verify"])
    assert r.exit_code == 1 and "seq 2" in r.output


def test_sync_command_reports_config_errors(monkeypatch: pytest.MonkeyPatch, seen_home: Path) -> None:
    from seen_core import paths

    paths.ensure_dir(seen_home)
    paths.config_toml().write_text("[sync]\nenabled = true\n")
    r = cli.invoke(app, ["sync"])
    assert r.exit_code == 2 and "server" in r.output


def test_docker_sync_snapshots_the_real_home_and_refuses_without_a_ledger(repo: Path, tmp_path: Path) -> None:
    dest = tmp_path / "dock"
    r = cli.invoke(app, ["docker-sync", "--dest", str(dest)])
    assert r.exit_code == 2 and not dest.exists()
    recorded(repo, tmp_path)
    from seen_core import paths

    (paths.home() / "team_key").write_text("SENTINEL-TEAM-KEY\n")
    assert "Snapshot" in invoke("docker-sync", "--dest", str(dest))
    assert (dest / "current" / "ledger.db").exists() and not (dest / "current" / "secret.key").exists()
    assert not (dest / "current" / "team_key").exists()  # the container must never hold the team key


def test_purge_reports_first_and_erases_only_with_yes(repo: Path, tmp_path: Path) -> None:
    recorded(repo, tmp_path)
    assert "Would erase" in invoke("purge", "--all")
    assert "Erased" in invoke("purge", "--all", "--yes")
    assert "0 changes" in invoke("purge", "--all")
    assert cli.invoke(app, ["purge"]).exit_code == 2
