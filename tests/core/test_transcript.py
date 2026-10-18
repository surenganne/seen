import json
import shutil
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from seen_core import pricing
from seen_core.transcript import parse_turn
from tests.conftest import FIXTURES

TR = FIXTURES / "transcripts"


def native(path: Path) -> dict[str, int]:
    for ln in path.read_text().splitlines():
        d = json.loads(ln)
        if d["type"] == "cost-state":
            m = next(iter(d["modelUsage"].values()))
            return {"tok_in": m["inputTokens"], "tok_out": m["outputTokens"],
                    "tok_cache_read": m["cacheReadInputTokens"], "tok_cache_write": m["cacheCreationInputTokens"]}
    raise AssertionError("no cost-state")


@pytest.mark.parametrize("name", ["run1", "subagent", "stopblock", "slash", "mcp", "bigout", "recall"])
def test_totals_reconcile_to_native(name: str) -> None:
    t = parse_turn(TR / f"{name}.jsonl", offset=0)
    got = {k: sum(u[k] for u in t.usage.values()) for k in ("tok_in", "tok_out", "tok_cache_read", "tok_cache_write")}
    assert got == native(TR / f"{name}.jsonl")


def test_subagent_usage_included() -> None:
    t = parse_turn(TR / "subagent.jsonl", offset=0)
    assert t.usage["claude-sonnet-5-5"]["tok_out"] == 454  # main 221 + subagent 233


def test_duplicate_message_ids_counted_once(tmp_path: Path) -> None:
    src = (TR / "run1.jsonl").read_text().splitlines()
    dup = [ln for ln in src if json.loads(ln)["type"] == "assistant"][0]
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(src + [dup, dup]) + "\n")
    assert parse_turn(p, 0).usage == parse_turn(TR / "run1.jsonl", 0).usage


def test_offset_slices_turn(tmp_path: Path) -> None:
    p = tmp_path / "t.jsonl"
    shutil.copy(TR / "run1.jsonl", p)
    first = parse_turn(p, 0)
    off = p.stat().st_size
    with open(p, "a") as f:
        f.write((TR / "run1.jsonl").read_text().replace('"id": "msg_', '"id": "msg2_'))
    assert parse_turn(p, off).usage == first.usage


def test_skills_and_slash_signals() -> None:
    r = parse_turn(TR / "recall.jsonl", 0)
    assert [s.name for s in r.skill_calls] == ["tick-skill"] * 10 + ["greet-skill"]
    s = parse_turn(TR / "slash.jsonl", 0)
    assert s.slash_commands == ["greet-skill"]
    sub = parse_turn(TR / "subagent.jsonl", 0)
    assert [(c.name, c.subagent) for c in sub.skill_calls] == [("greet-skill", True)]


def test_scan_texts_exclude_attachments_include_tool_results() -> None:
    m = parse_turn(TR / "mcp.jsonl", 0)
    kinds = {k for k, _, _ in m.scan_texts}
    assert "mcp" in kinds and "prompt" in kinds
    assert any("MCP-SENTINEL-55" in t for k, _, t in m.scan_texts if k == "mcp")


def test_version_and_last_text() -> None:
    r = parse_turn(TR / "run1.jsonl", 0)
    assert r.version and r.version.startswith("2.1")
    assert r.last_text.startswith("greeted")


@given(st.lists(st.one_of(st.text(), st.binary().map(lambda b: b.hex())), max_size=20))
def test_malformed_lines_never_crash(lines: list[str]) -> None:
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write("\n".join(lines))
    parse_turn(Path(f.name), 0)


def test_cost_uses_versioned_table() -> None:
    usage = {"claude-sonnet-5-5": {"tok_in": 1_000_000, "tok_out": 1_000_000, "tok_cache_read": 0,
                                   "tok_cache_write": 0, "cw_5m": 0, "cw_1h": 0}}
    cost, ver = pricing.cost(usage)
    assert cost == pytest.approx(12.0)
    assert ver == json.loads((Path(__file__).parents[2] / "pricing/prices.json").read_text())["version"]


def test_unknown_model_cost_is_none() -> None:
    cost, _ = pricing.cost({"mystery-model": {"tok_in": 5, "tok_out": 5, "tok_cache_read": 0, "tok_cache_write": 0,
                                              "cw_5m": 0, "cw_1h": 0}})
    assert cost is None
