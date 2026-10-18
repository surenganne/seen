from pathlib import Path

from seen_core.frontmatter import parse

ROOT = Path(__file__).resolve().parents[2]


def test_skill_front_matter_valid() -> None:
    fm, body = parse((ROOT / "plugin/skills/using-seen-memory/SKILL.md").read_text())
    assert fm["name"] == "using-seen-memory" and fm["description"].startswith("Use when")
    assert "verified_at" in body and "Never save" in body


def test_status_command_present() -> None:
    fm, body = parse((ROOT / "plugin/commands/status.md").read_text())
    assert fm["description"] and "seen status" in body
