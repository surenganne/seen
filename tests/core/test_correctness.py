"""Core correctness fixes from the 2026-10-19 audit (item 4)."""

import os
import threading
from pathlib import Path

import pytest

from seen_core import audit, paths, secret
from seen_core.memory import session as msess
from seen_core.skills import lock


def ev(i: int) -> dict:
    return {"type": "tool.call", "actor_kind": "agent", "actor_id": "u_1", "project_id": "p1", "session_id": "s1",
            "subject": f"Edit:{i}", "detail": {"n": i}}


def run_threads(n: int, fn) -> list[BaseException]:  # type: ignore[no-untyped-def]
    errs: list[BaseException] = []
    gate = threading.Barrier(n)

    def body(i: int) -> None:
        try:
            gate.wait()
            fn(i)
        except BaseException as e:  # noqa: BLE001 - the test reports whatever broke
            errs.append(e)

    ts = [threading.Thread(target=body, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return errs


# A. a retention prune must not read as tampering
def test_verify_survives_a_prune_that_removed_recorded_heads(seen_home: Path) -> None:
    audit.append([ev(i) for i in range(1, 4)])
    audit.record_head()  # head at seq 3
    audit.append([ev(i) for i in range(4, 10)])
    audit.prune_before_seq(6)  # removes seq 3, which audit-heads.log still names
    assert audit.verify().ok


def test_verify_still_catches_a_truncated_tail(seen_home: Path) -> None:
    audit.append([ev(i) for i in range(1, 6)])
    audit.record_head()
    import sqlite3

    c = sqlite3.connect(paths.audit_db(), isolation_level=None)
    c.execute("DROP TRIGGER audit_no_delete")
    c.execute("DELETE FROM audit_events WHERE seq=5")
    assert not audit.verify().ok


# B. the install key is created once, whatever races
def test_secret_key_is_identical_across_racing_creators(seen_home: Path) -> None:
    keys: list[bytes] = []
    errs = run_threads(16, lambda _i: keys.append(secret.key()))
    assert not errs and len(set(keys)) == 1 and len(keys) == 16
    assert paths.secret_key().read_bytes() == keys[0] and oct(paths.secret_key().stat().st_mode & 0o777) == "0o600"


def test_a_short_key_file_is_replaced_not_trusted(seen_home: Path) -> None:
    paths.ensure_dir(paths.home())
    paths.secret_key().write_bytes(b"short")
    assert len(secret.key()) == 32 and paths.secret_key().read_bytes() == secret.key()


# C. parallel hooks share one session state file
def test_session_state_survives_parallel_writers(seen_home: Path) -> None:
    errs = run_threads(8, lambda i: [msess.write("s", {"i": i, "n": n}) for n in range(40)])
    assert not errs and "i" in msess.read("s")


def test_modify_does_not_lose_updates(seen_home: Path) -> None:
    def add(i: int) -> None:
        for n in range(25):
            msess.modify("s", lambda st, tag=f"{i}-{n}": st.setdefault("ids", []).append(tag))

    assert not run_threads(8, add)
    assert len(msess.read("s")["ids"]) == 200


# D. a planted FIFO must not hang the pre-read scan
def test_pre_read_scan_skips_a_fifo(repo: Path, seen_home: Path) -> None:
    from seen_core import hook

    fifo = repo / "pipe"
    os.mkfifo(fifo)
    done: list[object] = []
    t = threading.Thread(target=lambda: done.append(hook._pre_read_scan({"session_id": "s"}, str(fifo),
                                                                           {"types": ["email"]}, str(repo))), daemon=True)
    t.start()
    t.join(3)
    assert done and done[0].code == 0  # type: ignore[attr-defined]


# E. lockfile approvals
@pytest.mark.parametrize("approved", [[""], ["abc"], ["zzzzzzz"], ["ABCDEF1"]])
def test_malformed_or_empty_approved_hashes_never_approve(approved: list[str]) -> None:
    lk = lock.Lockfile(approved={"tdd": approved})
    assert lock.status(lk, "tdd", "abcdef1" + "0" * 57) != "approved"


def test_seven_hex_prefix_still_approves() -> None:
    assert lock.status(lock.Lockfile(approved={"tdd": ["abcdef1"]}), "tdd", "abcdef1" + "0" * 57) == "approved"


# G. cost accuracy
def _asst(mid: str, ts: str, out: int, inp: int = 10, tool: str | None = None) -> dict:
    content = [{"type": "tool_use", "id": tool, "name": "Agent", "input": {}}] if tool else [{"type": "text", "text": "hi"}]
    return {"type": "assistant", "timestamp": ts, "message": {"id": mid, "model": "claude-sonnet-5-5", "content": content,
                                                              "usage": {"input_tokens": inp, "output_tokens": out}}}


def _result(tool: str, ts: str, agent: str) -> dict:
    return {"type": "user", "timestamp": ts, "toolUseResult": {"agentId": agent},
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool, "content": "ok"}]}}


def _write(path: Path, rows: list[dict]) -> int:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path.stat().st_size


def test_usage_uses_the_largest_streamed_value_per_message_id(tmp_path: Path) -> None:
    from seen_core.transcript import parse_turn

    tp = tmp_path / "t.jsonl"
    _write(tp, [_asst("m1", "2026-10-19T10:00:00Z", 1), _asst("m1", "2026-10-19T10:00:01Z", 50)])
    u = parse_turn(tp, 0).usage["claude-sonnet-5-5"]
    assert u["tok_out"] == 50 and u["tok_in"] == 10  # input counted once, output not left at the partial value


def test_a_resumed_subagent_is_only_counted_for_this_turn(tmp_path: Path) -> None:
    from seen_core.transcript import parse_turn

    tp = tmp_path / "t.jsonl"
    turn1 = [_asst("m1", "2026-10-19T10:00:00Z", 5, tool="tu1"), _result("tu1", "2026-10-19T10:00:40Z", "ag1")]
    off = _write(tp, turn1)
    _write(tp, [*turn1, _asst("m2", "2026-10-19T11:00:00Z", 10, tool="tu2"), _result("tu2", "2026-10-19T11:00:40Z", "ag1")])
    _write(tp.with_suffix("") / "subagents" / "agent-ag1.jsonl",
           [_asst("s1", "2026-10-19T10:00:30Z", 100), _asst("s2", "2026-10-19T11:00:30Z", 200)])
    assert parse_turn(tp, off).usage["claude-sonnet-5-5"]["tok_out"] == 210  # m2 + s2, not + s1


# F. racing ingests must not drop a whole audit batch
def test_appending_an_event_id_twice_is_a_noop_not_a_failed_batch(seen_home: Path) -> None:
    a = {**ev(1), "event_id": "turn1:file:a.py"}
    b = {**ev(2), "event_id": "turn1:file:b.py"}
    assert len(audit.append([a])) == 1
    stored = audit.append([a, b])  # the same turn ingested twice at once: a is already there
    assert [r["event_id"] for r in stored] == ["turn1:file:b.py"]
    assert audit.verify().ok and audit.verify().count == 2


# memory rewrites must not follow a symlinked .seen/memory out of the repo
def test_verify_refuses_a_symlinked_memory_folder(repo: Path, tmp_path: Path) -> None:
    from seen_core.memory import files

    outside = tmp_path / "outside"
    outside.mkdir()
    note = outside / "n1.md"
    note.write_text("---\nid: n1\ntype: decision\nfile_ref: null\nverified_at: null\n---\nbody\n")
    (repo / ".seen").mkdir()
    (repo / ".seen" / "memory").symlink_to(outside)
    before = note.read_text()
    with pytest.raises(OSError):
        files.verify(repo / ".seen" / "memory" / "n1.md", "2026-10-19T00:00:00Z")
    assert note.read_text() == before


# a forged checkpoint must not hide a truncated tail
def test_a_forged_checkpoint_cannot_vouch_for_truncated_events(seen_home: Path) -> None:
    import sqlite3

    audit.append([ev(i) for i in range(1, 6)])
    audit.record_head()  # head at seq 5
    c = sqlite3.connect(paths.audit_db(), isolation_level=None)
    c.execute("DROP TRIGGER audit_no_delete")
    c.execute("DELETE FROM audit_events WHERE seq=5")
    c.close()
    with pytest.raises(ValueError):
        audit.append([{"type": "audit.checkpoint", "actor_kind": "system",
                       "detail": {"pruned_from_seq": 1, "pruned_to_seq": 999, "last_pruned_hash": "0" * 64}}])
    # even if one is planted straight into the table, the claim is bounded by what is really missing
    c = sqlite3.connect(paths.audit_db(), isolation_level=None)
    c.execute("DROP TRIGGER IF EXISTS audit_no_update")
    last = c.execute("select seq, hash from audit_events order by seq desc limit 1").fetchone()
    row = {"seq": last[0] + 1, "event_id": "forged", "occurred_at": "t", "recorded_at": "t", "actor_kind": "system", "actor_id": None,
           "project_id": None, "session_id": None, "change_id": None, "type": "audit.checkpoint", "subject": None, "outcome": "ok",
           "detail_json": audit.canonical({"pruned_from_seq": 1, "pruned_to_seq": 999, "last_pruned_hash": "0" * 64}).decode(),
           "prev_hash": last[1]}
    row["hash"] = audit.compute_hash(row)
    c.execute(f"INSERT INTO audit_events({','.join([*audit.FIELDS, 'hash'])}) VALUES ({','.join('?' * (len(audit.FIELDS) + 1))})",
              [row[k] for k in [*audit.FIELDS, "hash"]])
    assert not audit.verify().ok


def test_a_malformed_checkpoint_does_not_crash_verification(seen_home: Path) -> None:
    import sqlite3

    audit.append([ev(1)])
    c = sqlite3.connect(paths.audit_db(), isolation_level=None)
    last = c.execute("select seq, hash from audit_events order by seq desc limit 1").fetchone()
    row = {"seq": 2, "event_id": "bad", "occurred_at": "t", "recorded_at": "t", "actor_kind": "system", "actor_id": None,
           "project_id": None, "session_id": None, "change_id": None, "type": "audit.checkpoint", "subject": None, "outcome": "ok",
           "detail_json": "{}", "prev_hash": last[1]}
    row["hash"] = audit.compute_hash(row)
    c.execute(f"INSERT INTO audit_events({','.join([*audit.FIELDS, 'hash'])}) VALUES ({','.join('?' * (len(audit.FIELDS) + 1))})",
              [row[k] for k in [*audit.FIELDS, "hash"]])
    audit.verify()  # must return a result, not raise


def test_verify_survives_two_prunes_with_heads_in_both_ranges(seen_home: Path) -> None:
    audit.append([ev(i) for i in range(1, 31)])
    audit.record_head()  # seq 30
    audit.prune_before_seq(10)
    audit.append([ev(i) for i in range(31, 41)])
    audit.record_head()
    audit.prune_before_seq(35)
    assert audit.verify().ok
