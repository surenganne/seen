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


def _aadhaar() -> str:
    from seen_core.pii import validators as v

    b = "23456789012"
    d = b + v.verhoeff_digit(b)
    return f"{d[:4]} {d[4:8]} {d[8:]}"


def test_p4b_3_block_mode_stops_prompt(scratch: tuple[Path, Path]) -> None:
    repo, home = scratch
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text('[pii]\nmode = "block"\n')
    r = claude(repo, home, f"My Aadhaar is {_aadhaar()}. Reply with the word PINEAPPLE.")
    out = r.stdout + r.stderr
    assert "UserPromptSubmit operation blocked by hook" in out and "Seen blocked this prompt" in out, out
    assert "\nPINEAPPLE" not in out.replace("Original prompt:", "")  # only the echoed prompt, no model reply
    assert "2345 6789" not in (home / "spool").glob("*.jsonl").__next__().read_text()


def test_p4b_3_warn_reaches_user_not_model(scratch: tuple[Path, Path]) -> None:
    repo, home = scratch
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text('[pii]\nmode = "warn"\n')
    r = claude(repo, home, f"Ignore this number {_aadhaar()}. Did you receive any message that starts with 'Seen:'? Answer yes or no only.",
               "--output-format", "stream-json", "--verbose")
    import json

    events = [json.loads(x) for x in r.stdout.splitlines() if x.startswith("{")]
    shown = [e for e in events if e.get("type") == "system" and "Seen: this prompt contains" in json.dumps(e)]
    result = next(e for e in events if e.get("type") == "result")["result"]
    assert shown, "user-facing systemMessage missing"
    assert result.strip().lower().startswith("no"), result


def test_pv10_blame_shows_agent_written_file(scratch: tuple[Path, Path]) -> None:
    import json
    import re

    repo, home = scratch
    r = claude(repo, home, "Create greeting.py with the Write tool (not Bash). It must contain a function greet(name) that returns "
                           "a formatted greeting, a function farewell(name), and a __main__ block that prints both for 'world'. "
                           "At least 8 lines. Then reply 'done.' only.")
    assert r.returncode == 0, r.stderr[-2000:]
    text = (repo / "greeting.py").read_text()
    git = ["git", "-c", "user.email=e@example.com", "-c", "user.name=e"]
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-qm", "greeting"], cwd=repo, check=True)
    seen = shutil.which("seen") or str(ROOT / ".venv/bin/seen")
    b = subprocess.run([seen, "blame", "greeting.py", "--json"], cwd=repo, env={**os.environ, "SEEN_HOME": str(home)},
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert b.returncode == 0, b.stderr
    blocks = json.loads(b.stdout)["blocks"]
    who: dict[int, str] = {n: blk["who"] for blk in blocks for n in range(blk["start"], blk["end"] + 1)}
    nontrivial = [i for i, ln in enumerate(text.splitlines(), 1) if len(re.sub(r"[^0-9A-Za-z]", "", ln)) >= 10]
    assert len(nontrivial) >= 3, text
    assert [who.get(i) for i in nontrivial] == ["agent"] * len(nontrivial), (who, text)
    first = next(blk for blk in blocks if blk["who"] == "agent")
    assert first["change_id"], first
