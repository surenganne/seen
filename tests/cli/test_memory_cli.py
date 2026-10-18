import json
from pathlib import Path

from seen_cli.main import app
from seen_core import audit
from tests.cli.test_cli import cli, invoke


def test_memory_add_list_verify_archive(repo: Path) -> None:
    invoke("init", cwd=repo)
    out = invoke("memory", "add", "--id", "stt-primary", "--type", "decision", "--file-ref", "agent/stt.py",
                 "--text", "STT primary is Sarvam streaming.", cwd=repo)
    assert "stt-primary" in out
    p = repo / ".seen/memory/stt-primary.md"
    assert p.exists() and "verified_at:" in p.read_text()
    listing = invoke("memory", "list", cwd=repo)
    assert "stt-primary" in listing and "unverified" in listing
    invoke("memory", "verify", "stt-primary", cwd=repo)
    assert "verified" in invoke("memory", "list", cwd=repo)
    ev = audit.query(type_="approval.memory_verified")
    assert ev and ev[0]["subject"] == "stt-primary" and "Sarvam" not in json.dumps(ev)
    invoke("memory", "archive", "stt-primary", cwd=repo)
    assert not p.exists() and (repo / ".seen/memory/archive/stt-primary.md").exists()
    assert audit.query(type_="approval.memory_archived")


def test_memory_add_rejects_bad_input(repo: Path) -> None:
    invoke("init", cwd=repo)
    import os

    old = os.getcwd()
    os.chdir(repo)
    try:
        r = cli.invoke(app, ["memory", "add", "--id", "Bad Id", "--type", "decision", "--text", "x"])
        assert r.exit_code != 0
        r = cli.invoke(app, ["memory", "add", "--id", "ok", "--type", "rumour", "--text", "x"])
        assert r.exit_code != 0
    finally:
        os.chdir(old)


def test_memory_list_shows_invalid_files(repo: Path) -> None:
    invoke("init", cwd=repo)
    (repo / ".seen/memory/broken.md").write_text("no front matter")
    assert "invalid" in invoke("memory", "list", cwd=repo)


def test_personal_memory(repo: Path, seen_home: Path) -> None:
    invoke("memory", "add", "--personal", "--id", "mine", "--type", "context", "--text", "my note", cwd=repo)
    assert list((seen_home / "memory").glob("*/mine.md"))
    assert "personal" in invoke("memory", "list", cwd=repo)
