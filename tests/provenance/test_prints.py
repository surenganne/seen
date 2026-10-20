from __future__ import annotations

from pathlib import Path

from seen_core.provenance.prints import added_lines, capture, fingerprint, is_trivial, normalize

KEY = b"k" * 32


def test_normalize_collapses_whitespace_and_crlf() -> None:
    assert normalize("\t  return   x +  y \r\n") == "return x + y"


def test_fingerprint_is_8_bytes_keyed_and_stable() -> None:
    a = fingerprint("def handler(event):", KEY)
    assert len(a) == 8 and a == fingerprint("  def  handler(event):\r", KEY)
    assert a != fingerprint("def handler(event):", b"j" * 32)


def test_trivial_lines_are_never_candidates() -> None:
    assert all(is_trivial(s) for s in ["}", "else:", "return", "", "x = 1"])  # fewer than 10 alphanumerics
    assert not is_trivial("result = compute(total)")


def test_write_adds_every_line_edit_adds_only_new_lines() -> None:
    assert added_lines("Write", {"content": "a\nb\n"}) == ["a", "b"]
    ti = {"old_string": "keep this line\nold line here", "new_string": "keep this line\nnew line here"}
    assert added_lines("Edit", ti) == ["new line here"]


def test_notebook_and_unsupported_tools() -> None:
    assert added_lines("MultiEdit", {"edits": []}) is None  # no MultiEdit tool in Claude Code (ADR 0018)
    assert added_lines("NotebookEdit", {"new_source": "cell line one", "edit_mode": "replace"}) == ["cell line one"]
    assert added_lines("NotebookEdit", {"new_source": "gone", "edit_mode": "delete"}) == []
    assert added_lines("Bash", {"command": "ls"}) is None


def test_capture_path_caps_and_binary(tmp_path: Path) -> None:
    root = str(tmp_path)
    c = capture("Write", {"file_path": f"{root}/src/a.py", "content": "line number one\nline number two\n"}, root, KEY)
    assert c is not None
    assert c["path"] == "src/a.py" and c["n"] == 2 and len(c["fps"]) == 2 and not c["capped"]
    assert all(len(f) == 16 for f in c["fps"])
    assert capture("Write", {"file_path": "/etc/passwd", "content": "x" * 50}, root, KEY) is None  # outside the repo
    assert capture("Write", {"file_path": f"{root}/b.bin", "content": "\0" + "x" * 50}, root, KEY) is None  # binary
    content = "\n".join(f"line number {i:06d}" for i in range(6000))
    big = capture("Write", {"file_path": f"{root}/c.py", "content": content}, root, KEY)
    assert big is not None and big["capped"] and big["fps"] == []


def test_minified_line_and_repeats(tmp_path: Path) -> None:  # Review Focus 4
    root = str(tmp_path)
    huge = capture("Write", {"file_path": f"{root}/m.js", "content": "a" * 500_000}, root, KEY)
    assert huge is not None and huge["n"] == 1 and not huge["capped"]  # one line, under the 1 MB cap
    rep = capture("Write", {"file_path": f"{root}/r.py", "content": "same repeated line\n" * 10_000}, root, KEY)
    assert rep is not None and rep["capped"] is True and rep["fps"] == []  # 10,000 candidates exceed the 5,000 cap
