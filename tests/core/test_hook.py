import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest

from seen_core import hook, paths
from tests.conftest import FIXTURES

P = FIXTURES / "hook_payloads"


def payload(name: str, cwd: Path, **over: object) -> dict:
    d = json.loads((P / f"{name}.json").read_text())
    d["cwd"] = str(cwd)
    for k in ("tool_input",):
        if k in d and "file_path" in d[k]:
            d[k]["file_path"] = d[k]["file_path"].replace("/work/demo-repo", str(cwd))
    d.update(over)
    return d


def run(event: str, d: dict) -> hook.Result:
    return hook.run(event, json.dumps(d).encode())


def spool(sid: str) -> list[dict]:
    f = paths.spool_file(sid)
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def test_replay_session_writes_expected_spool_lines(repo: Path) -> None:
    seq = [("session-start", "session_start"), ("prompt-submit", "user_prompt_submit"),
           ("pre-read", "pre_tool_use_read"), ("pre-edit", "pre_tool_use_edit"),
           ("post-tool", "post_tool_use_edit"), ("pre-skill", "pre_tool_use_skill"),
           ("post-tool", "post_tool_use_skill"), ("post-tool", "post_tool_use_bash"),
           ("stop", "stop"), ("session-end", "session_end")]
    sid = ""
    for ev, fx in seq:
        d = payload(fx, repo)
        sid = d["session_id"]
        r = run(ev, d)
        assert r.code == 0, (ev, r.stderr)
    evs = [x["ev"] for x in spool(sid)]
    assert evs[:2] == ["session_start", "turn_start"]
    assert "skill_start" in evs and evs.count("tool") == 3 and evs[-1] == "session_end"
    lines = spool(sid)
    start = next(x for x in lines if x["ev"] == "session_start")
    assert start["project_id"] and start["root"]
    tool = [x for x in lines if x["ev"] == "tool"]
    assert {t["tool"] for t in tool} == {"Edit", "Skill", "Bash"}
    bash = next(t for t in tool if t["tool"] == "Bash")
    assert bash["cmd0"] == "echo" and "command" not in json.dumps(bash)  # first token only, never args
    assert all("t" in x and "prompt_id" in x for x in lines if x["ev"] != "session_start")


def test_subagent_tool_events_carry_agent(repo: Path) -> None:
    d = payload("pre_tool_use_skill_subagent", repo)
    run("pre-skill", d)
    s = [x for x in spool(d["session_id"]) if x["ev"] == "skill_start"][0]
    assert s["skill"] == "greet-skill" and s["agent_id"] and s["trigger"] == "subagent"


def test_fail_open_on_garbage_and_logs(seen_home: Path) -> None:
    r = hook.run("post-tool", b"{not json")
    assert r.code == 0
    assert "JSONDecodeError" in paths.hook_log().read_text()


def test_fail_open_writes_capture_gap(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = payload("post_tool_use_edit", repo)

    def boom(*a: object, **k: object) -> None:
        raise RuntimeError("secret detail must not be logged to spool")

    monkeypatch.setattr(hook, "_on_post_tool", boom)
    assert run("post-tool", d).code == 0
    gap = [x for x in spool(d["session_id"]) if x["ev"] == "capture_gap"]
    assert gap and gap[0]["hook"] == "post-tool" and gap[0]["error"] == "RuntimeError"
    assert "secret detail" not in paths.spool_file(d["session_id"]).read_text()


def test_unknown_event_is_noop(repo: Path) -> None:
    assert run("bogus", payload("stop", repo)).code == 0


@pytest.mark.perf
def test_hook_latency_p95(repo: Path, tmp_path: Path) -> None:
    body = json.dumps(payload("post_tool_use_edit", repo)).encode()
    env = {"SEEN_HOME": str(tmp_path / "h"), "PATH": "/usr/bin:/bin"}
    ts = []
    for _ in range(25):
        t = time.perf_counter()
        subprocess.run([sys.executable, "-m", "seen_core.hook", "post-tool"], input=body, env=env, check=True)
        ts.append((time.perf_counter() - t) * 1000)
    ts.sort()
    p95 = ts[int(len(ts) * 0.95) - 1]
    print(f"hook p50={statistics.median(ts):.1f}ms p95={p95:.1f}ms")
    assert p95 < 150


def test_seen_home_is_private(repo: Path, seen_home: Path) -> None:
    run("post-tool", payload("post_tool_use_edit", repo))
    assert (seen_home.stat().st_mode & 0o777) == 0o700
    assert (paths.spool_file("x").parent.stat().st_mode & 0o777) == 0o700


def test_cmd0_skips_env_assignments() -> None:
    assert hook._cmd0("AWS_SECRET=abc /usr/bin/aws s3 ls") == "aws"


def test_prompt_submit_writes_before_snapshot(repo: Path) -> None:
    (repo / "dirty.txt").write_text("x\n")
    d = payload("user_prompt_submit", repo)
    run("prompt-submit", d)
    snap = json.loads(paths.snap_file(d["session_id"]).read_text())
    assert snap["prompt_id"] == d["prompt_id"]
    assert snap["before"]["head"] and snap["before"]["untracked"] == {"dirty.txt": 1}
    ts = [x for x in spool(d["session_id"]) if x["ev"] == "turn_start"][0]
    assert ts["head"] == snap["before"]["head"]


def test_background_scan_runs_isolated(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess as sp

    seen: dict = {}
    real = sp.Popen

    def fake(args, **kw):  # type: ignore[no-untyped-def]
        if "seen_core.skills.scan" in args:
            seen.update(args=args, **kw)
            return None
        return real(args, **kw)

    monkeypatch.delenv("SEEN_INVENTORY_SYNC", raising=False)
    monkeypatch.setattr(sp, "Popen", fake)
    run("session-start", payload("session_start", repo))
    assert "-I" in seen["args"] and seen["cwd"] == str(paths.home())


def test_session_hashes_skip_symlinked_lockfile(repo: Path, tmp_path: Path) -> None:
    (repo / ".seen").mkdir()
    secret = tmp_path / "elsewhere.json"
    secret.write_text("{}")
    (repo / ".seen/skills.lock.json").symlink_to(secret)
    d = payload("session_start", repo)
    run("session-start", d)
    assert spool(d["session_id"])[0]["lock_hash"] is None
