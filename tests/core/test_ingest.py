from pathlib import Path

import sqlalchemy as sa

from seen_core.db import ledger_engine
from tests.conftest import git
from tests.helpers import Replay


def rows(sql: str) -> list[dict]:
    with ledger_engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(sa.text(sql))]


def test_replayed_turn_writes_change_and_files(repo: Path, tmp_path: Path) -> None:
    git(repo, "remote", "add", "origin", "https://github.com/acme/demo.git")
    r = Replay(repo, tmp_path)
    r.start()
    r.prompt("add mul to calc")
    (repo / "a.py").write_text("one\ntwo\ndef mul(a, b):\n    return a * b\n")
    (repo / "GREETINGS.txt").write_text("hello\n")
    r.fire("post-tool", "post_tool_use_edit", tool_input={"file_path": str(repo / "a.py")})
    r.model_works()
    assert r.stop().code == 0

    ch = rows("select * from changes")
    assert len(ch) == 1
    c = ch[0]
    assert c["session_id"] == "sess-1" and c["seq"] == 1
    assert (c["tok_in"], c["tok_out"], c["tok_cache_read"], c["tok_cache_write"]) == (12, 733, 105739, 22468)
    assert c["model"] == "claude-sonnet-5-5" and c["cost_usd"] > 0 and c["price_version"]
    assert c["summary"] == "greeted"
    assert c["git_head_before"] and c["git_status"] == "uncommitted"
    files = {f["path"]: (f["added"], f["removed"]) for f in rows("select * from change_files")}
    assert files == {"a.py": (2, 0), "GREETINGS.txt": (1, 0)}
    assert rows("select * from projects")[0]["remote"] == "github.com/acme/demo"
    assert rows("select tool from sessions")[0]["tool"] == "claude-code"


def test_prompt_never_stored_raw_by_default(repo: Path, tmp_path: Path) -> None:
    r = Replay(repo, tmp_path)
    r.start()
    r.prompt("my email is sentinel.person@corp.test please fix")
    r.model_works()
    r.stop()
    assert "sentinel.person@corp.test" not in str(rows("select prompt_text from changes"))


def test_second_turn_is_seq_2_and_only_its_tokens(repo: Path, tmp_path: Path) -> None:
    r = Replay(repo, tmp_path)
    r.start()
    for _ in range(2):
        r.prompt()
        r.model_works()
        r.stop()
    ch = rows("select seq, tok_out from changes order by seq")
    assert ch == [{"seq": 1, "tok_out": 733}, {"seq": 2, "tok_out": 733}]


def test_stop_is_idempotent(repo: Path, tmp_path: Path) -> None:
    r = Replay(repo, tmp_path)
    r.start()
    r.prompt()
    r.model_works()
    r.stop()
    r.stop(stop_hook_active=True)
    assert len(rows("select id from changes")) == 1


def test_session_end_closes_session_and_reconciles_commit(repo: Path, tmp_path: Path) -> None:
    r = Replay(repo, tmp_path)
    r.start()
    r.prompt()
    (repo / "b.py").write_text("b\n")
    r.model_works()
    r.stop()
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "c")
    r.fire("session-end", "session_end")
    assert rows("select ended_at from sessions")[0]["ended_at"]
    assert rows("select git_status from changes")[0]["git_status"] == "committed"


def test_first_writes_survive_a_stale_check(seen_home: Path) -> None:
    """Two sessions can both see 'no row yet' for a new project or skill: the second insert must not fail."""
    from seen_core.db import ledger_session
    from seen_core.db.models import Project, Skill, SkillVersion
    from seen_core.ingest import _insert_ignore

    with ledger_session() as db:
        for _ in range(2):  # the second call is the loser of the race
            _insert_ignore(db, Project, id="p1", name="demo")
            _insert_ignore(db, Skill, id="s1", first_seen="t")
            _insert_ignore(db, SkillVersion, skill_id="s1", hash="h", first_seen="t")
        db.commit()
    assert len(rows("select * from projects")) == 1
    assert len(rows("select * from skills")) == 1 and len(rows("select * from skill_versions")) == 1
