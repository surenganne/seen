from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import pytest

from seen_core import paths, spool
from seen_core.provenance import prints
from tests.helpers import Replay

KEY = b"k" * 32


def prints_lines(sid: str = "sess-1") -> list[dict]:  # type: ignore[type-arg]
    return [x for x in spool.read(sid) if x["ev"] == "prints"]


def test_write_tool_spools_prints_not_text(repo: Path, tmp_path: Path) -> None:
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    secret_line = "api_token = 'sk-live-AAAABBBBCCCCDDDD'"
    rp.fire("post-tool", "post_tool_use_write", tool_input={"file_path": str(repo / "a.py"), "content": secret_line + "\nprint('hello world')\n"})
    lines = spool.read("sess-1")
    p = [x for x in lines if x["ev"] == "prints"][0]
    assert p["path"] == "a.py" and p["n"] == 2 and all(len(f) == 16 for f in p["fps"])
    assert p["capped"] is False and "tool_use_id" in p
    assert "sk-live" not in json.dumps(lines) and "hello world" not in json.dumps(lines)


def test_disabled_writes_nothing(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    paths.ensure_dir(seen_home)
    paths.config_toml().write_text("[provenance]\nenabled = false\n")
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    rp.fire("post-tool", "post_tool_use_write", tool_input={"file_path": str(repo / "a.py"), "content": "a long enough line\n"})
    assert not prints_lines()


def test_bash_writes_nothing(repo: Path, tmp_path: Path) -> None:
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    rp.fire("post-tool", "post_tool_use_write", tool_name="Bash", tool_input={"command": "echo a long enough line > a.py"})
    assert not prints_lines()


def test_a_failing_capture_still_records_the_tool_call(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("seen_core.provenance.prints.capture", lambda *a, **k: 1 / 0)
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    assert rp.fire("post-tool", "post_tool_use_write").code == 0
    assert [x for x in spool.read("sess-1") if x["ev"] == "tool"]
    assert not prints_lines()


def test_a_capped_call_spools_a_capped_line_without_fps(repo: Path, tmp_path: Path) -> None:
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    content = "\n".join(f"value_{i} = compute({i})" for i in range(5001)) + "\n"
    rp.fire("post-tool", "post_tool_use_write", tool_input={"file_path": str(repo / "a.py"), "content": content})
    p = prints_lines()[0]
    assert p["capped"] is True and p["fps"] == [] and p["n"] == 5001


@pytest.mark.perf
def test_capture_adds_under_5ms_p50_for_a_200_line_edit() -> None:
    ti = {"file_path": "/r/a.py", "old_string": "", "new_string": "\n".join(f"value_{i} = compute({i})" for i in range(200))}
    times = []
    for _ in range(50):
        t0 = time.perf_counter()
        prints.capture("Edit", ti, "/r", KEY)
        times.append(time.perf_counter() - t0)
    assert statistics.median(times) < 0.005
