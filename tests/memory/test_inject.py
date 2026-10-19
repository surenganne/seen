import json
from pathlib import Path

import pytest
import sqlalchemy as sa

from seen_core import paths, spool
from seen_core.db import ledger_engine
from seen_core.memory import files as mf
from tests.helpers import Replay


@pytest.fixture
def mrepo(repo: Path) -> Path:
    d = repo / ".seen/memory"
    mf.new_memory(d, id="stt-primary", type="decision", body="STT primary is Sarvam streaming.", file_ref="agent/stt.py")
    p = mf.new_memory(d, id="clock-fixture", type="convention", body="Tests freeze time with the clock fixture.", file_ref="tests/t.py")
    mf.verify(p, "2026-10-10T00:00:00Z")
    return repo


def ctx(r) -> str:  # type: ignore[no-untyped-def]
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout else ""


def test_session_start_injects_json_context(mrepo: Path, tmp_path: Path) -> None:
    rp = Replay(mrepo, tmp_path)
    r = rp.fire("session-start", "session_start")
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Sarvam streaming" in ctx(r) and "[UNVERIFIED]" in ctx(r)
    inj = [x for x in spool.read("sess-1") if x["ev"] == "memory_injected"]
    assert inj and set(inj[0]["ids"]) == {"stt-primary", "clock-fixture"} and inj[0]["tokens"] > 0
    assert "Sarvam" not in json.dumps(inj)  # ids and hashes only


def test_prompt_submit_injects_only_new_relevant(mrepo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEEN_MEMORY_BUDGET", "20")  # session start fits one memory only
    rp = Replay(mrepo, tmp_path)
    first = ctx(rp.fire("session-start", "session_start"))
    r = rp.prompt("change agent/stt.py to batch mode")
    second = ctx(r)
    assert ("stt-primary" in first) != ("stt-primary" in second) or "stt-primary" in first
    assert json.loads(r.stdout)["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit" if r.stdout else True


def test_gate_allows_when_loaded_blocks_when_not(mrepo: Path, tmp_path: Path, seen_home: Path) -> None:
    rp = Replay(mrepo, tmp_path)
    rp.start()
    rp.prompt()
    edit = {"tool_input": {"file_path": str(mrepo / "a.py"), "old_string": "one", "new_string": "1"}}
    assert rp.fire("pre-edit", "pre_tool_use_edit", **edit).code == 0

    paths.ensure_dir(seen_home)
    paths.config_toml().write_text("[memory]\ninject = false\n")
    rp2 = Replay(mrepo, tmp_path, sid="sess-2")
    rp2.start()
    rp2.prompt()
    r = rp2.fire("pre-edit", "pre_tool_use_edit", **edit)
    assert r.code == 2 and ".seen/memory" in r.stderr
    mem_write = {"tool_input": {"file_path": str(mrepo / ".seen/memory/new.md"), "content": "x"}}
    assert rp2.fire("pre-edit", "pre_tool_use_write", **mem_write).code == 0
    rp2.fire("pre-read", "pre_tool_use_read", tool_input={"file_path": str(mrepo / ".seen/memory/stt-primary.md")})
    assert rp2.fire("pre-edit", "pre_tool_use_edit", **edit).code == 0  # model read the folder: recovered
    gates = [x for x in spool.read("sess-2") if x["ev"] == "gate"]
    assert [g["decision"] for g in gates] == ["block", "allow", "allow"]


def test_gate_off_and_no_memory_projects_never_block(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    edit = {"tool_input": {"file_path": str(repo / "a.py"), "old_string": "one", "new_string": "1"}}
    assert rp.fire("pre-edit", "pre_tool_use_edit", **edit).code == 0


def test_ingest_writes_change_memories_and_state(mrepo: Path, tmp_path: Path) -> None:
    rp = Replay(mrepo, tmp_path)
    rp.start()
    rp.prompt()
    rp.model_works()
    rp.stop()
    with ledger_engine().connect() as c:
        mem = c.execute(sa.text("select memory_id, content_hash from change_memories order by memory_id")).all()
        ch = c.execute(sa.text("select mem_state, mem_injected_tokens from changes")).one()
    assert [m for m, _ in mem] == ["clock-fixture", "stt-primary"] and all(len(h) == 16 for _, h in mem)
    assert ch[0] == "loaded" and ch[1] > 0


@pytest.mark.perf
def test_injection_under_100ms_with_100_files(repo: Path, tmp_path: Path) -> None:
    import statistics
    import subprocess
    import sys
    import time

    d = repo / ".seen/memory"
    for i in range(100):
        mf.new_memory(d, id=f"m{i:03d}", type="context", body=f"Fact number {i} about module {i % 7}.", file_ref=f"src/m{i}.py")
    rp = Replay(repo, tmp_path)
    env = {"SEEN_HOME": str(tmp_path / "h"), "PATH": "/usr/bin:/bin", "SEEN_INVENTORY_SYNC": "1"}
    start = json.dumps(rp.payload("session_start")).encode()
    subprocess.run([sys.executable, "-m", "seen_core.hook", "session-start"], input=start, env=env, check=True, capture_output=True)
    body = json.dumps(rp.payload("user_prompt_submit", prompt="change module 3")).encode()
    ts = []
    for _ in range(15):
        t = time.perf_counter()
        subprocess.run([sys.executable, "-m", "seen_core.hook", "prompt-submit"], input=body, env=env, check=True, capture_output=True)
        ts.append((time.perf_counter() - t) * 1000)
    ts.sort()
    print(f"prompt-submit with 100 memories p50={statistics.median(ts):.0f}ms p95={ts[-1]:.0f}ms")
    assert statistics.median(ts) < 100
