import hashlib
import os
from pathlib import Path

import pytest

from seen_core import paths
from seen_core.project import normalise_remote, resolve_project
from tests.conftest import git


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/Org/Repo.git", "github.com/org/repo"),
    ("https://user:tok3n@github.com/org/repo", "github.com/org/repo"),
    ("git@github.com:Org/Repo.git", "github.com/org/repo"),
    ("ssh://git@gitlab.example.com:2222/team/app.git", "gitlab.example.com:2222/team/app"),
    ("https://github.com/org/repo/", "github.com/org/repo"),
])
def test_normalise_remote(url: str, expected: str) -> None:
    assert normalise_remote(url) == expected


def test_https_and_ssh_remotes_give_same_id(repo: Path, tmp_path: Path) -> None:
    git(repo, "remote", "add", "origin", "https://github.com/org/repo.git")
    a = resolve_project(repo)
    git(repo, "remote", "set-url", "origin", "git@github.com:org/repo.git")
    b = resolve_project(repo)
    assert a is not None and b is not None
    assert a.id == b.id == hashlib.sha1(b"github.com/org/repo").hexdigest()[:12]
    assert a.remote == "github.com/org/repo"
    assert a.name == "repo"


def test_no_remote_uses_toplevel_realpath(repo: Path) -> None:
    (repo / "sub").mkdir()
    p = resolve_project(repo / "sub")
    assert p is not None
    assert p.id == hashlib.sha1(os.path.realpath(repo).encode()).hexdigest()[:12]
    assert p.remote is None
    assert Path(p.root) == Path(os.path.realpath(repo))


def test_worktree_maps_to_same_project(repo: Path, tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", str(wt), "-b", "feature")
    assert resolve_project(wt).id == resolve_project(repo).id  # type: ignore[union-attr]


def test_not_a_repo_returns_none(tmp_path: Path) -> None:
    assert resolve_project(tmp_path) is None


def test_paths_follow_seen_home(seen_home: Path) -> None:
    assert paths.home() == seen_home
    assert paths.ledger_db() == seen_home / "ledger.db"
    assert paths.audit_db() == seen_home / "audit.db"
    assert paths.spool_file("s1") == seen_home / "spool" / "s1.jsonl"


def test_redact_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/dev")
    assert paths.redact_home("/Users/dev/repos/x/a.py") == "~/repos/x/a.py"
    assert paths.redact_home("/opt/x") == "/opt/x"
