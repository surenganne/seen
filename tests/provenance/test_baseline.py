from __future__ import annotations

from pathlib import Path

from seen_core.provenance import baseline, prints
from tests.conftest import git

KEY = b"k" * 32
A, B, C, D, E = (f"baseline_line_{n} = compute_value({n}, scale={n * 3})" for n in "ABCDE")


def fps(*texts: str) -> list[str]:
    return [prints.fingerprint(t, KEY).hex() for t in texts]


def repo_with(tmp_path: Path, text: str) -> tuple[Path, str]:
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "core.py").write_text(text)
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    return r, git(r, "rev-parse", "HEAD").strip()


def test_baseline_lines_are_dropped(tmp_path: Path) -> None:
    r, head = repo_with(tmp_path, f"{A}\n{B}\n{C}\nx = 1\n")
    assert baseline.subtract(str(r), head, "core.py", KEY, fps(A, B, C, D, E)) == fps(D, E)


def test_trivial_baseline_lines_are_ignored(tmp_path: Path) -> None:
    r, head = repo_with(tmp_path, f"{A}\nx = 1\n")
    triv = fps("x = 1")  # a trivial line is never fingerprinted by baseline, so a spooled equal one stays
    assert baseline.subtract(str(r), head, "core.py", KEY, fps(A, D) + triv) == fps(D) + triv


def test_empty_baselines_remove_nothing(tmp_path: Path) -> None:
    r, head = repo_with(tmp_path, f"{A}\n")
    want = fps(A, D)
    assert baseline.subtract(str(r), None, "core.py", KEY, want) == want  # no head_before
    assert baseline.subtract(str(r), head, "missing.py", KEY, want) == want  # file absent at head
    assert baseline.subtract(str(r), "0" * 40, "core.py", KEY, want) == want  # git failure
    assert baseline.subtract(str(tmp_path / "nope"), head, "core.py", KEY, want) == want  # not a repo
    assert baseline.subtract(None, head, "core.py", KEY, want) == want
    assert baseline.subtract(str(r), "--bad", "core.py", KEY, want) == want  # option-looking ref


def test_over_cap_baseline_removes_nothing(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    r, head = repo_with(tmp_path, f"{A}\n")
    monkeypatch.setattr(baseline, "MAX_BYTES", 5)
    assert baseline.subtract(str(r), head, "core.py", KEY, fps(A)) == fps(A)
