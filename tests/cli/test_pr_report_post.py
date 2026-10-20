"""`seen pr-report --post`: confirmation, a stubbed `gh` on PATH (the real one is never called), one count-only audit event."""

import json
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seen_cli import main as cli_main
from seen_cli.main import app
from seen_core import audit
from tests.conftest import git
from tests.provenance.scenarios import Scene
from tests.provenance.test_scenarios import SCENARIOS

cli = CliRunner()


@pytest.fixture
def stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A `gh` that records argv and stdin to a file, exits with $GH_STUB_CODE, and prints a fixed error line on failure."""
    d = tmp_path / "bin"
    d.mkdir()
    rec = tmp_path / "gh-calls.jsonl"
    g = d / "gh"
    g.write_text(f"#!{sys.executable}\n"
                 "import json, os, sys\n"
                 f"open({str(rec)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:], 'stdin': sys.stdin.read()}}) + '\\n')\n"
                 "code = int(os.environ.get('GH_STUB_CODE', '0'))\n"
                 "if code:\n"
                 "    sys.stderr.write('no pull requests found\\nsecond line\\n')\n"
                 "sys.exit(code)\n")
    g.chmod(g.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    return rec


def calls(rec: Path) -> list[dict[str, object]]:
    return [json.loads(x) for x in rec.read_text().splitlines()] if rec.exists() else []


def events() -> list[dict[str, object]]:
    return audit.query(type_="provenance.reported")


@pytest.fixture
def scene(tmp_path: Path) -> Scene:
    s = Scene(tmp_path, "sq")
    SCENARIOS["squash merge"](s)
    return s


@pytest.fixture(autouse=True)
def tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_main, "_stdin_is_tty", lambda: True)


def run(cwd: Path, *args: str, input: str | None = None) -> tuple[int, str, str]:
    old = os.getcwd()
    try:
        os.chdir(cwd)
        r = cli.invoke(app, ["pr-report", "--base", "HEAD~1", *args], input=input, catch_exceptions=False)
    finally:
        os.chdir(old)
    return r.exit_code, r.stdout, r.stderr


def one_line(err: str) -> None:
    assert len(err.strip().splitlines()) == 1 and "Traceback" not in err


def test_declining_posts_nothing(scene: Scene, stub: Path) -> None:
    for answer in ("n\n", "\n", ""):  # no, default, EOF
        code, out, _ = run(scene.root, "--post", input=answer)
        assert code == 0 and "agent 10" in out
    assert calls(stub) == [] and events() == []


def test_accepting_posts_once_and_records_counts_only(scene: Scene, stub: Path) -> None:
    code, out, err = run(scene.root, "--post", input="y\n")
    assert code == 0, err
    c = calls(stub)
    assert len(c) == 1 and c[0]["argv"] == ["pr", "comment", "--body-file", "-"]
    body = str(c[0]["stdin"])
    assert body.strip() and body.strip() in out  # exactly the comment that was shown
    ev = events()
    assert len(ev) == 1 and ev[0]["actor_kind"] == "user" and ev[0]["subject"] in (None, "")
    d = json.loads(ev[0]["detail_json"]) if "detail_json" in ev[0] else ev[0]["detail"]
    assert set(d) == {"added", "requests"} and all(isinstance(v, int) for v in d.values())
    assert d["added"] >= 10 and d["requests"] >= 1


def test_yes_skips_the_question(scene: Scene, stub: Path) -> None:
    code, _, _ = run(scene.root, "--post", "--yes", input="")
    assert code == 0 and len(calls(stub)) == 1 and len(events()) == 1


def test_missing_gh_exits_2_with_hint(scene: Scene, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    (empty / "git").symlink_to(shutil.which("git") or "git")  # git stays reachable, gh does not
    monkeypatch.setenv("PATH", str(empty))
    code, _, err = run(scene.root, "--post", "--yes")
    assert code == 2 and "https://cli.github.com" in err
    one_line(err)
    assert events() == []


def test_gh_failure_exits_2_without_event(scene: Scene, stub: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_STUB_CODE", "1")
    code, _, err = run(scene.root, "--post", "--yes")
    assert code == 2 and "no pull requests found" in err and "second line" not in err
    one_line(err)
    assert len(calls(stub)) == 1 and events() == []


def test_head_must_be_the_checked_out_branch(scene: Scene, stub: Path) -> None:
    git(scene.root, "branch", "other", "HEAD~1")
    code, _, err = run(scene.root, "--head", "other", "--post", "--yes")
    assert code == 2
    one_line(err)
    assert calls(stub) == [] and events() == []


def test_non_interactive_without_yes_refuses(scene: Scene, stub: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_main, "_stdin_is_tty", lambda: False)
    code, _, err = run(scene.root, "--post", input="y\n")
    assert code == 2
    one_line(err)
    assert calls(stub) == [] and events() == []


def test_post_with_json_is_a_usage_error(scene: Scene, stub: Path) -> None:
    code, _, err = run(scene.root, "--post", "--yes", "--format", "json")
    assert code == 2
    one_line(err)
    assert calls(stub) == [] and events() == []


def test_no_shell(scene: Scene, stub: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess
    seen: list[tuple[object, dict[str, object]]] = []
    real = subprocess.run

    def spy(*a: object, **k: object) -> object:
        if a and isinstance(a[0], list) and a[0][:1] == ["gh"]:
            seen.append((a[0], k))
        return real(*a, **k)  # type: ignore[call-overload]

    monkeypatch.setattr(subprocess, "run", spy)
    assert run(scene.root, "--post", "--yes")[0] == 0
    (argv, kw), = seen
    assert argv == ["gh", "pr", "comment", "--body-file", "-"] and not kw.get("shell") and kw["timeout"] == 30
    assert Path(str(kw["cwd"])).resolve() == scene.root.resolve()
