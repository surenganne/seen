import os
import subprocess
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def seen_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets its own SEEN_HOME; nothing ever touches ~/.seen."""
    home = tmp_path / "seen-home"
    monkeypatch.setenv("SEEN_HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    monkeypatch.setenv("SEEN_ORG_SKILLS_DIRS", str(tmp_path / "org-skills"))
    monkeypatch.setenv("SEEN_NO_UPDATE_CHECK", "1")  # tests never reach the network
    return home


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "a.py").write_text("one\ntwo\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "init")
    return r
