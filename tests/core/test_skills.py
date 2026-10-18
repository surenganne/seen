import json
import os
from pathlib import Path

import pytest

from seen_core.frontmatter import parse
from seen_core.skills.hashing import hash_folder
from seen_core.skills.scan import claude_dir, discover


def mkskill(root: Path, name: str, body: str = "do it", extra: dict[str, str] | None = None, desc: str = "d") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\nallowed-tools: Read, Bash\n---\n{body}\n")
    for rel, txt in (extra or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(txt)
    return d


def test_hash_stable_and_changes_with_bundled_script(tmp_path: Path) -> None:
    d = mkskill(tmp_path, "s1", extra={"scripts/run.py": "print(1)\n"})
    h1 = hash_folder(d)
    assert h1 == hash_folder(d) and len(h1) == 64
    (d / "scripts/run.py").write_text("print(2)\n")
    assert hash_folder(d) != h1


def test_hash_ignores_junk(tmp_path: Path) -> None:
    d = mkskill(tmp_path, "s1")
    h = hash_folder(d)
    for junk in (".git/HEAD", "node_modules/x/i.js", "__pycache__/a.pyc", ".DS_Store", "sub/.DS_Store"):
        (d / junk).parent.mkdir(parents=True, exist_ok=True)
        (d / junk).write_text("junk")
    assert hash_folder(d) == h


def test_hash_skips_symlink_escaping_folder(tmp_path: Path) -> None:
    d = mkskill(tmp_path, "s1")
    h = hash_folder(d)
    secret = tmp_path / "outside.txt"
    secret.write_text("x")
    (d / "link").symlink_to(secret)
    assert hash_folder(d) == h
    (d / "inner").symlink_to(d / "SKILL.md")
    assert hash_folder(d) != h  # an in-folder link is content


def test_frontmatter_parse() -> None:
    fm, body = parse("---\nname: x\ndescription: \"A: b\"\ntags: [a, b]\n---\nhello\n")
    assert fm == {"name": "x", "description": "A: b", "tags": ["a", "b"]} and body == "hello\n"
    assert parse("no front matter") == ({}, "no front matter")


def test_discover_all_kinds(tmp_path: Path, repo: Path) -> None:
    cfg = claude_dir()
    mkskill(cfg / "skills", "user-skill")
    mkskill(repo / ".claude/skills", "proj-skill")
    (repo / ".claude/commands").mkdir(parents=True)
    (repo / ".claude/commands/shout.md").write_text("---\ndescription: Shout\n---\nSHOUT $ARGUMENTS\n")
    mkskill(Path(os.environ["SEEN_ORG_SKILLS_DIRS"]) / "skills", "org-skill")
    inst = tmp_path / "cache/mkt/plug/1.2.3"
    mkskill(inst / "skills", "plug-skill")
    (cfg / "plugins").mkdir(parents=True)
    (cfg / "plugins/installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {"plug@mkt": [{"scope": "user", "installPath": str(inst), "version": "1.2.3"}]}}))
    found = {s.id: s for s in discover(repo)}
    assert found["user-skill"].kind == "user"
    assert found["proj-skill"].kind == "project" and found["proj-skill"].allowed_tools == "Read, Bash"
    assert found["shout"].kind == "project" and found["shout"].description == "Shout"
    assert found["org-skill"].kind == "org"
    assert found["plug:plug-skill"].kind == "plugin" and found["plug:plug-skill"].origin == "plug@1.2.3"
    assert all(len(s.hash) == 64 for s in found.values())
    assert found["user-skill"].path.startswith(("~", "/"))


def test_discover_uses_cache_until_file_changes(tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = mkskill(claude_dir() / "skills", "u1")
    first = discover(repo)
    from seen_core.skills import scan

    calls = []
    real = scan.hash_folder
    monkeypatch.setattr(scan, "hash_folder", lambda p: calls.append(p) or real(p))
    assert discover(repo) == first and calls == []
    (d / "SKILL.md").write_text("---\nname: u1\ndescription: d2\n---\nnew\n")
    os.utime(d / "SKILL.md", ns=(1, 10**18))
    again = {s.id: s for s in discover(repo)}
    assert calls and again["u1"].hash != first[0].hash


def test_inventory_reaches_ledger_and_drift_adds_version(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlalchemy as sa

    from seen_core.db import ledger_engine
    from tests.helpers import Replay

    monkeypatch.setenv("SEEN_INVENTORY_SYNC", "1")
    d = mkskill(repo / ".claude/skills", "greet-skill", extra={"run.sh": "echo 1\n"})
    r = Replay(repo, tmp_path)
    r.start()
    r.prompt()
    r.model_works()
    r.stop()
    (d / "run.sh").write_text("echo 2\n")
    os.utime(d / "run.sh", ns=(1, 10**18))
    r2 = Replay(repo, tmp_path, sid="sess-2")
    r2.start()
    r2.prompt()
    r2.model_works()
    r2.stop()
    with ledger_engine().connect() as c:
        sk = c.execute(sa.text("select id, kind from skills where id='greet-skill'")).all()
        vers = c.execute(sa.text("select hash from skill_versions where skill_id='greet-skill'")).all()
    assert sk == [("greet-skill", "project")]
    assert len(vers) == 2


def test_project_skill_cannot_claim_plugin_namespace(repo: Path) -> None:
    d = repo / ".claude/skills/sneaky"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: security:review\ndescription: x\n---\nx\n")
    ids = {s.id for s in discover(repo)}
    assert "security:review" not in ids and "sneaky" in ids


def test_command_symlink_and_huge_files_skipped(repo: Path, tmp_path: Path) -> None:
    cm = repo / ".claude/commands"
    cm.mkdir(parents=True)
    outside = tmp_path / "secret.md"
    outside.write_text("---\ndescription: s\n---\n")
    (cm / "link.md").symlink_to(outside)
    (cm / "big.md").write_text("x" * (2 * 1024 * 1024))
    (cm / "ok.md").write_text("---\ndescription: fine\n---\n")
    ids = {s.id for s in discover(repo)}
    assert ids == {"ok"}


def test_sync_never_downgrades_kind(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_core import ingest
    from seen_core.db import ledger_session
    from seen_core.db.models import Skill

    with ledger_session() as db:
        db.add(Skill(id="review", kind="user", origin=None))
        db.commit()
    monkeypatch.setattr(ingest, "inventory", lambda pid: [{"id": "review", "kind": "project", "origin": None, "path": "p",
                                                         "description": "d", "allowed_tools": None, "hash": "h" * 64}])
    with ledger_session() as db:
        ingest._sync_inventory(db, "p1")
        db.commit()
        assert db.get(Skill, "review").kind == "user"


def test_folder_or_nested_command_cannot_spoof_plugin_id(repo: Path, tmp_path: Path) -> None:
    inst = tmp_path / "cache/mkt/sec/1.0"
    mkskill(inst / "skills", "review")
    (claude_dir() / "plugins").mkdir(parents=True)
    (claude_dir() / "plugins/installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {"sec@mkt": [{"installPath": str(inst), "version": "1.0"}]}}))
    (repo / ".claude/commands/sec").mkdir(parents=True)
    (repo / ".claude/commands/sec/review.md").write_text("---\ndescription: fake\n---\n")
    mkskill(repo / ".claude/skills", "sec:review2")
    found = {s.id: s for s in discover(repo)}
    assert found["sec:review"].kind == "plugin"
    assert "sec:review2" not in found
