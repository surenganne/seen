"""Final review fix pass: inputs the recorded fixtures never contained (one test per Important finding)."""

import json
import os
import time
from pathlib import Path

import pytest
import sqlalchemy as sa

from seen_core import audit, config, ingest, paths, spool
from seen_core.db import ledger_engine
from seen_core.gitdelta import delta, snapshot
from tests.conftest import git
from tests.helpers import Replay


def q(sql: str) -> list[tuple]:
    with ledger_engine().connect() as c:
        return [tuple(r) for r in c.execute(sa.text(sql))]


# 1. non-ASCII and space-containing file names
def test_non_ascii_file_names_counted_and_scanned(repo: Path, tmp_path: Path) -> None:
    (repo / "dätei a.txt").write_text("1\n2\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "u")
    before = snapshot(repo)
    (repo / "dätei a.txt").write_text("1\n2\n3\n")
    (repo / "nëw.txt").write_text("x\ny\n")
    assert delta(before, snapshot(repo, base=before["head"])) == {"dätei a.txt": (1, 0), "nëw.txt": (2, 0)}
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    (repo / "nëw.txt").write_text("mail u.person@corp.test.in\n")
    rp.model_works()
    rp.stop()
    assert ("nëw.txt",) in q("select path from change_files")
    assert ("nëw.txt", "email") in q("select source_ref, type from pii_findings where source_kind='diff_added'")


# 2. custom regex ReDoS from a committed pii.yaml
def test_catastrophic_custom_rule_rejected(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    from seen_core.pii.projectcfg import load_project

    (repo / ".seen").mkdir()
    (repo / ".seen/pii.yaml").write_text('custom_rules:\n  - id: bad\n    pattern: "(a+)+$"\n  - id: ok\n    pattern: "\\\\bMRN\\\\d{6}\\\\b"\n')
    assert [r["id"] for r in load_project(repo)["custom_rules"]] == ["ok"]
    paths.ensure_dir(seen_home)
    paths.config_toml().write_text('[pii]\nmode = "block"\n')
    rp = Replay(repo, tmp_path)
    rp.start()
    t = time.perf_counter()
    rp.prompt("a" * 40 + "!")
    assert time.perf_counter() - t < 2


# 3. very long sessions
def test_audit_ingest_survives_40k_spool_lines(repo: Path, tmp_path: Path) -> None:
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    f = paths.spool_file("sess-1")
    with open(f, "a") as fh:
        for i in range(40_000):
            fh.write(json.dumps({"t": spool.now(), "ev": "tool", "tool": "Read", "prompt_id": "p1", "tool_use_id": f"t{i}"}) + "\n")
    rp.model_works()
    rp.stop()
    assert len(audit.query(type_="tool.call", limit=100_000)) == 40_000
    assert audit.query(type_="turn.end")
    rp.stop(stop_hook_active=True)  # second Stop only converts new lines
    assert len(audit.query(type_="tool.call", limit=100_000)) == 40_000


# 4. human decisions survive re-ingest
def test_mark_test_data_survives_reingest(repo: Path, tmp_path: Path) -> None:
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt("mail a.person@corp.test.in")
    (repo / "x.txt").write_text("b.person@corp.test.in\n")
    rp.model_works()
    rp.stop()
    with ledger_engine().begin() as c:
        c.execute(sa.text("update pii_findings set status='test_data'"))
    rp.stop(stop_hook_active=True)
    ingest.finish_turn("sess-1")
    assert {s for (s,) in q("select status from pii_findings")} == {"test_data"}
    assert q("select pii_count, pii_state from changes") == [(0, "none")]


# 5. worktrees: repo-local files and git checks come from the worktree
def test_worktree_uses_its_own_checkout(repo: Path, tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", str(wt), "-b", "feat")
    (wt / ".seen").mkdir()
    (wt / ".seen/policies.yaml").write_text('- id: pol\n  title: t\n  paths: ["llm/**"]\n  require_skill: s\n  mode: report\n')
    rp = Replay(wt, tmp_path)
    rp.start()
    rp.prompt()
    (wt / "llm").mkdir()
    (wt / "llm/x.py").write_text("x\n")
    rp.model_works()
    rp.stop()
    assert q("select path from change_files") == [("llm/x.py",)]
    assert [m for (m,) in q("select met from policy_results")] == [0]
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "w")
    rp.fire("session-end", "session_end")
    assert q("select git_status from changes") == [("committed",)]


# 6. raw assistant text never stays in the spool
def test_last_message_redacted_in_spool(repo: Path, tmp_path: Path) -> None:
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    rp.model_works()
    rp.stop(last_assistant_message="Wrote to raw.person@corp.test.in. Then a lot more text.")
    text = paths.spool_file("sess-1").read_text()
    assert "raw.person" not in text and "[EMAIL]" in text


# 7. retention is applied; ended spools are cleaned up
def test_retention_prunes_and_cleans_spool(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    rp = Replay(repo, tmp_path, sid="old")
    rp.start()
    rp.prompt()
    rp.model_works()
    rp.stop()
    rp.fire("session-end", "session_end")
    old = paths.spool_file("old")
    past = time.time() - 30 * 86400
    os.utime(old, (past, past))
    rp2 = Replay(repo, tmp_path, sid="new")
    rp2.start()
    rp2.prompt()
    rp2.model_works()
    rp2.stop()
    rp2.fire("session-end", "session_end")
    assert not old.exists() and paths.spool_file("new").exists()
    assert audit.verify().ok and config.load()["audit"]["retention_days"] == 365


def test_retention_days_applied(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(audit, "prune_older_than", lambda d: calls.append(d))
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.fire("session-end", "session_end")
    assert calls == [365]


# 8. lockfile planted as a symlink to an endless device
def test_symlinked_lockfile_is_ignored_fast(repo: Path, tmp_path: Path) -> None:
    from seen_core.skills import lock

    (repo / ".seen").mkdir()
    (repo / ".seen/skills.lock.json").symlink_to("/dev/zero")
    t = time.perf_counter()
    assert lock.load(repo).blocked == []
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    assert rp.fire("pre-skill", "pre_tool_use_skill").code == 0
    assert time.perf_counter() - t < 2


# 9. many large untracked files
def test_untracked_counting_has_a_total_budget(repo: Path) -> None:
    for i in range(40):
        (repo / f"big{i}.csv").write_bytes(b"x,y\n" * (512 * 1024))  # 2 MB each
    t = time.perf_counter()
    s = snapshot(repo)
    assert time.perf_counter() - t < 1.5
    assert len(s["untracked"]) == 40 and all(v == 0 for v in s["untracked"].values())


@pytest.mark.parametrize("pat", ["((a+))+$", "(?:(?:a+))+", "(a*)*b", "(?:a|aa)+$", "((ab|a)c?)*x", "(x+x+)+y",
                                 "(?>(?:a+)+b)", "()(?:(?(1)a+|a))+$", r"(a)\1+"])
def test_nested_quantifiers_rejected_at_any_depth(pat: str) -> None:
    from seen_core.pii.projectcfg import safe_pattern

    assert not safe_pattern(pat)


@pytest.mark.parametrize("pat", [r"\bMRN[:# ]*\d{6,10}\b", r"\bUHID-\d{8}\b", r"(?i)patient id: [A-Z]{2}\d{6}"])
def test_ordinary_rules_still_allowed(pat: str) -> None:
    from seen_core.pii.projectcfg import safe_pattern

    assert safe_pattern(pat)
