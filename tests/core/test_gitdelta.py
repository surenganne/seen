import subprocess
from pathlib import Path

import pytest
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


def test_repo_fsmonitor_config_is_not_executed(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    git(repo, "config", "core.fsmonitor", f"touch {marker}; false")
    snapshot(repo)
    assert not marker.exists()


def test_symlink_and_fifo_not_read(repo: Path, tmp_path: Path) -> None:
    import os

    big = tmp_path / "outside.txt"
    big.write_text("x\n" * 10)
    (repo / "link.txt").symlink_to(big)
    os.mkfifo(repo / "pipe")
    s = snapshot(repo)
    assert s["untracked"].get("link.txt") == 0 and s["untracked"].get("pipe", 0) == 0


def test_repo_clean_filter_is_not_executed(repo: Path, tmp_path: Path) -> None:
    from seen_core import gitutil

    gitutil.filter_overrides.cache_clear()
    marker = tmp_path / "filter-pwned"
    git(repo, "config", "filter.evil.clean", f"sh -c 'touch {marker}; cat'")
    git(repo, "config", "filter.evil.process", f"sh -c 'touch {marker}'")
    (repo / ".gitattributes").write_text("* filter=evil\n")
    (repo / "a.py").write_text("changed\n")
    snapshot(repo)
    assert not marker.exists()


@pytest.mark.parametrize("driver", ["evil", "ev il.x"])
def test_filter_via_info_attributes_and_odd_names_not_executed(repo: Path, tmp_path: Path, driver: str) -> None:
    from seen_core import gitutil

    gitutil.filter_overrides.cache_clear()
    marker = tmp_path / "m"
    git(repo, "config", f"filter.{driver}.clean", f"sh -c 'touch {marker}; cat'")
    (repo / ".git/info").mkdir(exist_ok=True)
    (repo / ".git/info/attributes").write_text(f'* filter="{driver}"\n' if " " in driver else f"* filter={driver}\n")
    (repo / "a.py").write_text("changed\n")
    snapshot(repo)
    assert not marker.exists()
