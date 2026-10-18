import subprocess
from pathlib import Path

from seen_core.gitdelta import delta, snapshot
from tests.conftest import git


def test_edit_existing_file(repo: Path) -> None:
    before = snapshot(repo)
    (repo / "a.py").write_text("one\nTWO\nthree\n")
    d = delta(before, snapshot(repo, base=before["head"]))
    assert d == {"a.py": (2, 1)}


def test_edit_via_bash(repo: Path) -> None:
    before = snapshot(repo)
    subprocess.run("printf 'x\\n' >> a.py", shell=True, cwd=repo, check=True)
    assert delta(before, snapshot(repo, base=before["head"])) == {"a.py": (1, 0)}


def test_new_untracked_file_and_delete(repo: Path) -> None:
    before = snapshot(repo)
    (repo / "new.txt").write_text("1\n2\n3\n")
    (repo / "a.py").unlink()
    assert delta(before, snapshot(repo, base=before["head"])) == {"new.txt": (3, 0), "a.py": (0, 2)}


def test_preexisting_dirty_lines_not_counted(repo: Path) -> None:
    (repo / "a.py").write_text("one\ntwo\nhuman\n")
    (repo / "scratch.txt").write_text("h\n")
    before = snapshot(repo)
    (repo / "a.py").write_text("one\ntwo\nhuman\nagent\n")
    assert delta(before, snapshot(repo, base=before["head"])) == {"a.py": (1, 0)}


def test_revert_in_turn_caught_by_hint(repo: Path) -> None:
    before = snapshot(repo)
    (repo / "a.py").write_text("changed\n")
    (repo / "a.py").write_text("one\ntwo\n")
    after = snapshot(repo, base=before["head"])
    assert delta(before, after) == {}
    assert delta(before, after, hints=[str(repo / "a.py")], root=repo) == {"a.py": (0, 0)}


def test_commit_during_turn_still_counted(repo: Path) -> None:
    before = snapshot(repo)
    (repo / "b.py").write_text("b\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "agent commit")
    after = snapshot(repo, base=before["head"])
    assert after["head"] != before["head"]
    assert delta(before, after) == {"b.py": (1, 0)}


def test_binary_file_touched_with_zero_lines(repo: Path) -> None:
    before = snapshot(repo)
    (repo / "img.bin").write_bytes(b"\x00\x01\x02")
    git(repo, "add", "img.bin")
    assert delta(before, snapshot(repo, base=before["head"])) == {"img.bin": (0, 0)}


def test_not_a_repo(tmp_path: Path) -> None:
    assert snapshot(tmp_path) == {"head": None, "numstat": {}, "untracked": {}}
