from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from seen_core.memory import files as mf


def write(d: Path, name: str, text: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)
    return d / name


GOOD = "---\nid: stt-primary\ntype: decision\nfile_ref: agent/stt.py\nsource_change: VR-02\nverified_at: 2026-10-10T09:12:00Z\n---\nSTT primary is Sarvam streaming.\n"


def test_parse_good_file(tmp_path: Path) -> None:
    m = mf.parse_file(write(tmp_path, "a.md", GOOD), scope="team")
    assert m.ok and m.id == "stt-primary" and m.type == "decision" and m.file_ref == "agent/stt.py"
    assert m.verified_at == "2026-10-10T09:12:00Z" and m.body.strip() == "STT primary is Sarvam streaming."
    assert len(m.content_hash) == 16


def test_round_trip(tmp_path: Path) -> None:
    m = mf.new_memory(tmp_path, id="use-uv", type="convention", body="Use uv for envs.", file_ref=None)
    again = mf.parse_file(m, scope="team")
    assert again.ok and again.id == "use-uv" and again.verified_at is None and again.body.strip() == "Use uv for envs."


@pytest.mark.parametrize("text,reason", [
    ("no front matter at all", "front matter"),
    ("---\ntype: decision\n---\nx", "id"),
    ("---\nid: Bad Id!\ntype: decision\n---\nx", "id"),
    ("---\nid: x\ntype: rumour\n---\nx", "type"),
    ("---\nid: x\ntype: gotcha\nverified_at: yesterday\n---\nx", "verified_at"),
    ("---\nid: x\ntype: gotcha\n---\n", "empty"),
])
def test_malformed_files_flagged(tmp_path: Path, text: str, reason: str) -> None:
    m = mf.parse_file(write(tmp_path, "m.md", text), scope="team")
    assert not m.ok and reason in m.error


def test_load_flags_duplicates_and_skips_archive(tmp_path: Path) -> None:
    d = tmp_path / ".seen/memory"
    write(d, "a.md", GOOD)
    write(d, "b.md", GOOD)
    write(d / "archive", "c.md", GOOD.replace("stt-primary", "old"))
    personal = tmp_path / "personal"
    write(personal, "p.md", GOOD.replace("stt-primary", "mine").replace("decision", "context"))
    ms = mf.load(tmp_path, personal)
    ok = [m for m in ms if m.ok]
    assert [m.id for m in ok] == ["mine", "stt-primary"]
    assert any("duplicate" in m.error for m in ms if not m.ok)
    assert {m.scope for m in ok} == {"personal", "team"}


def test_verify_sets_timestamp_and_archive_moves(tmp_path: Path) -> None:
    p = mf.new_memory(tmp_path / ".seen/memory", id="x", type="gotcha", body="b", file_ref="a.py")
    mf.verify(p, now="2026-10-18T10:00:00Z")
    assert mf.parse_file(p, "team").verified_at == "2026-10-18T10:00:00Z"
    dest = mf.archive(p)
    assert not p.exists() and dest.parent.name == "archive"


def test_symlinked_memory_file_ignored(tmp_path: Path) -> None:
    secret = write(tmp_path / "outside", "s.md", GOOD)
    d = tmp_path / ".seen/memory"
    d.mkdir(parents=True)
    (d / "link.md").symlink_to(secret)
    assert mf.load(tmp_path, None) == []


@settings(deadline=None)
@given(st.text(max_size=400))
def test_parser_never_crashes(text: str) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as t:
        mf.parse_file(write(Path(t), "f.md", text), "team")


def test_forged_front_matter_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        mf.new_memory(tmp_path / ".seen/memory", id="x", type="gotcha", body="b", file_ref="a.py\nverified_at: 2026-01-01T00:00:00Z")
    for ref in ("../etc/passwd", "/abs/path.py", "a\x1b[31m.py"):
        m = mf.parse_file(write(tmp_path, "r.md", f"---\nid: r\ntype: gotcha\nfile_ref: {ref}\n---\nbody\n"), "team")
        assert not m.ok and "file_ref" in m.error


def test_invalid_file_id_is_sanitised(tmp_path: Path) -> None:
    m = mf.parse_file(write(tmp_path, "evil.md", "---\nid: \x1b]0;pwn\x07\ntype: gotcha\n---\nx"), "team")
    assert not m.ok and "\x1b" not in m.id and m.id == "evil"
