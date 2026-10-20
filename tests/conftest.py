import os
import sqlite3
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from seen_core import paths

FIXTURES = Path(__file__).parent / "fixtures"
REAL_HOME = Path.home() / ".seen"
REAL_LEDGER = REAL_HOME / "ledger.db"


def assert_not_real_home() -> None:
    """Scenario builders and scripts call this first: they write ledgers, so SEEN_HOME must be a scratch dir."""
    env = Path(os.environ.get("SEEN_HOME") or "~/.seen").expanduser()
    if env.resolve() == REAL_HOME.resolve():
        raise RuntimeError(f"SEEN_HOME is the real {REAL_HOME}: set SEEN_HOME to a scratch directory "
                           "(for example $(mktemp -d)) before running tests, scenarios or scripts")


def _real_project_names() -> list[str] | None:
    """Read-only (immutable: the live WAL is never opened or created). None when there is no ledger or it cannot be read."""
    try:
        c = sqlite3.connect(f"file:{REAL_LEDGER}?immutable=1", uri=True)
        try:
            return [r[0] for r in c.execute("select name from projects order by name")]
        finally:
            c.close()
    except (sqlite3.Error, OSError):
        return None


@pytest.fixture(scope="session", autouse=True)
def _real_ledger_untouched() -> Iterator[None]:
    before = _real_project_names()
    yield
    after = _real_project_names()
    if before is not None and after != before:
        pytest.fail(f"the real {REAL_LEDGER} project list changed during this test run "
                    f"(added: {sorted(set(after or []) - set(before))}; removed: {sorted(set(before) - set(after or []))}). "
                    "A test or script used the real SEEN_HOME (monkeypatch.undo() reverts the isolation), "
                    "or your own Seen session added a project meanwhile.", pytrace=False)


@pytest.fixture(autouse=True)
def _home_guard(seen_home: Path, tmp_path: Path) -> Iterator[None]:
    """paths.home() must resolve inside this test's tmp dir. Own MonkeyPatch, so a test's monkeypatch.undo() cannot lift it."""
    real, tmp = paths.home, tmp_path.resolve()

    def guarded() -> Path:
        h = real()
        if not h.resolve().is_relative_to(tmp):
            raise AssertionError(f"SEEN_HOME resolves to {h}, outside the test tmp dir: the isolation was lifted "
                                 "(monkeypatch.undo() reverts the seen_home fixture; use monkeypatch.context())")
        return h

    mp = pytest.MonkeyPatch()
    mp.setattr(paths, "home", guarded)
    try:
        yield
    finally:
        mp.undo()


@pytest.fixture(autouse=True)
def seen_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets its own SEEN_HOME; nothing ever touches ~/.seen."""
    home = tmp_path / "seen-home"
    monkeypatch.setenv("SEEN_HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    monkeypatch.setenv("SEEN_ORG_SKILLS_DIRS", str(tmp_path / "org-skills"))
    monkeypatch.setenv("SEEN_NO_UPDATE_CHECK", "1")  # tests never reach the network
    return home


def git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com", **(env or {})}
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
