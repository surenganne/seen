"""Headless end-to-end: real Claude Code, the real plugin, a scratch repo and SEEN_HOME.

Manual or nightly (costs a few cents): uv run pytest -m e2e tests/e2e
Never touches ~/.seen, ~/.claude plugin installs or ~/.local/bin: the plugin is loaded with
--plugin-dir and the hook binary comes from this workspace via SEEN_HOOK_BIN.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.e2e


def claude(repo: Path, home: Path, prompt: str, *extra: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    hook_bin = shutil.which("seen-hook") or str(ROOT / ".venv/bin/seen-hook")
    e = {**os.environ, "SEEN_HOME": str(home), "SEEN_HOOK_BIN": hook_bin, **(env or {})}
    for k in ("CLAUDE_CONFIG_DIR", "SEEN_ORG_SKILLS_DIRS"):  # unit-test isolation; e2e needs the real login
        if os.environ.get(k, "").startswith(str(home.parent)):
            e.pop(k)
    return subprocess.run(["claude", "-p", prompt, "--plugin-dir", str(ROOT / "plugin"), "--setting-sources", "project",
                           "--model", "sonnet", "--max-budget-usd", "1", "--permission-mode", "acceptEdits", *extra],
                          cwd=repo, env=e, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)


@pytest.fixture
def scratch(tmp_path: Path) -> tuple[Path, Path]:
    if not shutil.which("claude"):
        pytest.skip("claude CLI not installed")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "-c", "user.email=e@example.com", "-c", "user.name=e", "commit", "-qam", "init", "--allow-empty"],
                   cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=e@example.com", "-c", "user.name=e", "commit", "-qm", "calc"], cwd=repo, check=True)
    return repo, tmp_path / "seen-home"


def test_known_edit_lands_in_ledger(scratch: tuple[Path, Path]) -> None:
    repo, home = scratch
    r = claude(repo, home, "Add a function mul(a, b) returning a*b to calc.py using the Edit tool. Reply 'done.' only.")
    assert r.returncode == 0, r.stderr[-2000:]
    db = sqlite3.connect(home / "ledger.db")
    ch = db.execute("select id, tok_out, model, summary from changes").fetchall()
    assert len(ch) == 1 and ch[0][1] > 0 and ch[0][2], ch
    files = db.execute("select path, added from change_files").fetchall()
    assert ("calc.py", 3) in files or any(p == "calc.py" and a >= 2 for p, a in files), files
    a = sqlite3.connect(home / "audit.db")
    types = [t for (t,) in a.execute("select type from audit_events order by seq")]
    assert types[0] == "session.start" and "turn.end" in types and "file.changed" in types


def _memory(repo: Path, mid: str, body: str) -> None:
    d = repo / ".seen/memory"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{mid}.md").write_text(f"---\nid: {mid}\ntype: context\nverified_at: 2026-10-10T00:00:00Z\n---\n{body}\n")


def test_p3_3_model_quotes_injected_memory(scratch: tuple[Path, Path]) -> None:
    repo, home = scratch
    _memory(repo, "deploy-codeword", "The deploy codeword for this project is HERON-58.")
    r = claude(repo, home, "What is the deploy codeword in this project's memory? Reply with the codeword only. Do not use tools.")
    assert r.returncode == 0 and "HERON-58" in r.stdout, r.stdout
    db = sqlite3.connect(home / "ledger.db")
    assert db.execute("select memory_id from change_memories").fetchall() == [("deploy-codeword",)]
    assert db.execute("select mem_state from changes").fetchone()[0] == "loaded"


def test_p3_4_gate_blocks_until_memory_read(scratch: tuple[Path, Path]) -> None:
    repo, home = scratch
    _memory(repo, "calc-style", "Functions in calc.py have one-line docstrings.")
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text("[memory]\ninject = false\n")
    r = claude(repo, home, "Add a function mul(a, b) returning a*b to calc.py using the Edit tool. "
                           "If a hook blocks you, follow its instructions and retry. Then reply 'done.'")
    assert r.returncode == 0, r.stderr[-1500:]
    assert "def mul" in (repo / "calc.py").read_text()
    import json

    gates = [json.loads(x) for f in (home / "spool").glob("*.jsonl") for x in f.read_text().splitlines()]
    decisions = [g["decision"] for g in gates if g.get("ev") == "gate"]
    assert decisions[0] == "block" and "allow" in decisions, decisions


def test_p3_5_agent_saves_memory_as_unverified(scratch: tuple[Path, Path]) -> None:
    repo, home = scratch
    _memory(repo, "existing", "Placeholder so the memory folder exists.")
    r = claude(repo, home, "We decided: all money amounts are stored as integer paise, never floats. "
                           "Save this as project memory following the using-seen-memory skill, then reply 'saved.'")
    assert r.returncode == 0, r.stderr[-1500:]
    from seen_core.memory import files as mf

    new = [m for m in mf.load(repo, None) if m.ok and m.id != "existing"]
    assert new and new[0].verified_at is None and "paise" in new[0].body.lower(), [m.__dict__ for m in mf.load(repo, None)]


def test_p4_6_enforce_runs_required_skill_then_stops(scratch: tuple[Path, Path]) -> None:
    repo, home = scratch
    (repo / ".claude/skills/llm-review").mkdir(parents=True)
    (repo / ".claude/skills/llm-review/SKILL.md").write_text(
        "---\nname: llm-review\ndescription: Use when asked to review LLM code. Replies 'reviewed'.\n---\nReply 'reviewed'. Do not use tools.\n")
    (repo / ".seen").mkdir()
    (repo / ".seen/policies.yaml").write_text(
        '- id: pol-llm\n  title: Review LLM code\n  paths: ["llm/**"]\n  require_skill: llm-review\n  mode: enforce\n')
    r = claude(repo, home, "Create llm/prompt.py containing the line PROMPT = 'hi' using the Write tool. Then reply 'done.'")
    assert r.returncode == 0, r.stderr[-1500:]
    import json

    spool = [json.loads(x) for f in (home / "spool").glob("*.jsonl") for x in f.read_text().splitlines()]
    stop_blocks = [x for x in spool if x.get("ev") == "gate" and x.get("hook") == "stop"]
    assert len(stop_blocks) == 1  # exactly once: no loop
    db = sqlite3.connect(home / "ledger.db")
    assert db.execute("select met from policy_results").fetchall() == [(1,)]
    assert ("llm-review",) in db.execute("select skill_id from skill_invocations").fetchall()
