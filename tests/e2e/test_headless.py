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
