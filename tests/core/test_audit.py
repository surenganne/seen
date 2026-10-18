import sqlite3
import time
from pathlib import Path

import pytest
from seen_core import audit, paths


def ev(i: int, **kw: object) -> dict:
    return {"type": "tool.call", "actor_kind": "agent", "actor_id": "u_1", "project_id": "p1", "session_id": "s1",
            "subject": f"Edit:{i}", "outcome": "ok", "detail": {"tool": "Edit", "n": i}, **kw}


@pytest.fixture
def chain(seen_home: Path) -> Path:
    audit.append([ev(i) for i in range(1, 21)])
    return paths.audit_db()


def raw(db: Path) -> sqlite3.Connection:
    c = sqlite3.connect(db, isolation_level=None)
    c.execute("PRAGMA writable_schema=0")
    return c


def drop_guards(c: sqlite3.Connection) -> None:
    c.execute("DROP TRIGGER audit_no_update")
    c.execute("DROP TRIGGER audit_no_delete")


def test_clean_chain_verifies(chain: Path) -> None:
    r = audit.verify()
    assert r.ok and r.count == 20 and len(r.head) == 64


def test_first_event_prev_is_zeros(chain: Path) -> None:
    first = raw(chain).execute("select prev_hash from audit_events order by seq limit 1").fetchone()[0]
    assert first == "0" * 64


def test_update_and_delete_blocked_by_triggers(chain: Path) -> None:
    c = raw(chain)
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("update audit_events set outcome='blocked' where seq=3")
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("delete from audit_events where seq=3")


def test_edit_detected_at_seq(chain: Path) -> None:
    c = raw(chain)
    drop_guards(c)
    c.execute("update audit_events set outcome='blocked' where seq=7")
    r = audit.verify()
    assert not r.ok and r.break_seq == 7 and r.expected != r.found


def test_delete_detected_at_seq(chain: Path) -> None:
    c = raw(chain)
    drop_guards(c)
    c.execute("delete from audit_events where seq=5")
    r = audit.verify()
    assert not r.ok and r.break_seq == 6


def test_reorder_detected(chain: Path) -> None:
    c = raw(chain)
    drop_guards(c)
    a = c.execute("select * from audit_events where seq=9").fetchone()
    b = c.execute("select * from audit_events where seq=10").fetchone()
    c.execute("delete from audit_events where seq in (9,10)")
    cols = ",".join("?" * len(a))
    c.execute(f"insert into audit_events values ({cols})", (9, *b[1:]))
    c.execute(f"insert into audit_events values ({cols})", (10, *a[1:]))
    r = audit.verify()
    assert not r.ok and r.break_seq == 9


def test_truncate_tail_detected_via_heads_log(chain: Path) -> None:
    audit.record_head()
    c = raw(chain)
    drop_guards(c)
    c.execute("delete from audit_events where seq > 15")
    r = audit.verify()
    assert not r.ok and r.break_seq == 16


def test_detail_rejects_content() -> None:
    with pytest.raises(ValueError):
        audit.append([ev(1, detail={"prompt": "hello"})])
    with pytest.raises(ValueError):
        audit.append([ev(1, detail={"tool": "x" * 500})])


def test_prune_writes_checkpoint_and_still_verifies(chain: Path) -> None:
    audit.prune_before_seq(11)
    r = audit.verify()
    assert r.ok and r.count == 11  # 10 kept + checkpoint
    cp = [e for e in audit.query() if e["type"] == "audit.checkpoint"]
    assert cp and cp[0]["detail"]["pruned_to_seq"] == 10


def test_verify_100k_under_10s(seen_home: Path) -> None:
    for chunk in range(10):
        audit.append([ev(i) for i in range(chunk * 10000, (chunk + 1) * 10000)])
    t = time.perf_counter()
    r = audit.verify()
    dt = time.perf_counter() - t
    assert r.ok and r.count == 100_000
    assert dt < 10, dt


def test_subject_and_odd_types_checked(seen_home: Path) -> None:
    with pytest.raises(ValueError):
        audit.append([ev(1, subject="x" * 500)])
    with pytest.raises(ValueError):
        audit.append([ev(1, detail={"tool": ("a", "b" * 500)})])
    with pytest.raises(ValueError):
        audit.append([ev(1, detail={"tool": object()})])
