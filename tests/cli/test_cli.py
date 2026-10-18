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
    assert (s / "memory").is_dir() and (s / "policies.yaml").exists() and (s / "pii.yaml").exists()
    assert json.loads((s / "skills.lock.json").read_text()) == {"approved": {}, "blocked": []}
    assert ".cache/" in (s / ".gitignore").read_text()
    settings = json.loads((repo / ".claude/settings.json").read_text())
    assert {"Write(.seen/memory/**)", "Edit(.seen/memory/**)"} <= set(settings["permissions"]["allow"])
    (repo / ".claude/settings.json").write_text(json.dumps({**settings, "model": "keep-me"}))
    invoke("init", cwd=repo)
    again = json.loads((repo / ".claude/settings.json").read_text())
    assert again["model"] == "keep-me" and again["permissions"]["allow"].count("Write(.seen/memory/**)") == 1
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
