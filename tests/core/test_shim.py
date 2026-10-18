import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHIM = ROOT / "plugin/bin/seen-hook"


def test_shim_fails_open_without_seen_cli(tmp_path: Path) -> None:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "SEEN_HOME": str(tmp_path / "h")}
    r = subprocess.run([str(SHIM), "session-start"], input=b"{}", env=env, capture_output=True)
    assert r.returncode == 0
    assert "not installed" in json.loads(r.stdout)["systemMessage"]
    assert "seen-hook not found" in (tmp_path / "h/log/hook.log").read_text()


def test_shim_execs_seen_hook(tmp_path: Path) -> None:
    fake = tmp_path / "fake-hook"
    fake.write_text("#!/bin/sh\necho ran:$1\n")
    fake.chmod(0o755)
    r = subprocess.run([str(SHIM), "stop"], input="{}", env={"PATH": "/usr/bin:/bin", "SEEN_HOOK_BIN": str(fake)},
                       capture_output=True, text=True)
    assert r.stdout.strip() == "ran:stop"


def test_hooks_json_matches_findings() -> None:
    h = json.loads((ROOT / "plugin/hooks/hooks.json").read_text())["hooks"]
    assert set(h) == {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SessionEnd"}
    assert all("${CLAUDE_PLUGIN_ROOT}/bin/seen-hook" in x["hooks"][0]["command"] for v in h.values() for x in v)
