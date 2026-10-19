from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from seen_core import audit
from seen_core.db import ledger_session
from seen_core.db.models import Session

PID = "demo-payments"


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _open_session(sid: str, last_event: datetime) -> None:
    with ledger_session() as db:
        db.add(Session(id=sid, project_id=PID, started_at=_iso(last_event - timedelta(minutes=2)), tool_version="9.9.9"))
        db.commit()
    audit.append([{"type": "session.start", "actor_kind": "system", "actor_id": "u", "project_id": PID, "session_id": sid,
                   "occurred_at": _iso(last_event - timedelta(minutes=2))},
                  {"type": "tool.call", "actor_kind": "agent", "actor_id": "u", "project_id": PID, "session_id": sid,
                   "subject": "Bash", "occurred_at": _iso(last_event)}])


def test_sessions_list_status_and_counts(client: TestClient) -> None:
    now = datetime.now(UTC)
    _open_session("live-1", now - timedelta(minutes=1))
    _open_session("stale-1", now - timedelta(hours=3))
    r = client.get(f"/api/projects/{PID}/sessions", params={"page_size": 200})
    assert r.status_code == 200
    items = {s["id"]: s for s in r.json()["items"]}
    assert items["live-1"]["status"] == "active" and items["live-1"]["tool_calls"] == 1
    assert items["live-1"]["last_event_at"] and items["live-1"]["tool_version"] == "9.9.9"
    assert items["stale-1"]["status"] == "incomplete"
    ended = [s for s in items.values() if s["ended_at"]]
    assert ended and all(s["status"] == "ended" for s in ended)
    seeded = next(s for s in ended if s["turns"] > 0)
    assert seeded["cost_usd"] > 0 and seeded["models"]
    starts = [s["started_at"] for s in r.json()["items"]]
    assert starts == sorted(starts, reverse=True)


def test_sessions_unknown_project(client: TestClient) -> None:
    assert client.get("/api/projects/nope/sessions").status_code == 404


def test_quiet_imported_session_reads_as_ended(client: TestClient) -> None:
    old = datetime.now(UTC) - timedelta(hours=2)
    with ledger_session() as db:
        db.add(Session(id="imp-quiet", project_id=PID, started_at=_iso(old), source="imported"))
        db.commit()
    items = {s["id"]: s for s in client.get(f"/api/projects/{PID}/sessions", params={"page_size": 200}).json()["items"]}
    assert items["imp-quiet"]["status"] == "ended" and items["imp-quiet"]["source"] == "imported"


def test_sessions_split_yours_and_background(client: TestClient) -> None:
    now = datetime.now(UTC)
    with ledger_session() as db:
        for sid, ep in (("mine-1", "cli"), ("bg-py", "sdk-py"), ("bg-cli", "sdk-cli"), ("unknown-1", None)):
            db.add(Session(id=sid, project_id=PID, started_at=_iso(now), entrypoint=ep))
        db.commit()
    every = client.get(f"/api/projects/{PID}/sessions", params={"page_size": 200}).json()
    by = {s["id"]: s for s in every["items"]}
    assert by["bg-py"]["background"] and by["bg-cli"]["background"] and by["bg-py"]["entrypoint"] == "sdk-py"
    assert not by["mine-1"]["background"] and not by["unknown-1"]["background"]
    yours = client.get(f"/api/projects/{PID}/sessions", params={"page_size": 200, "kind": "yours"}).json()
    bg = client.get(f"/api/projects/{PID}/sessions", params={"page_size": 200, "kind": "background"}).json()
    assert {"bg-py", "bg-cli"} <= {s["id"] for s in bg["items"]} and all(s["background"] for s in bg["items"])
    assert {"mine-1", "unknown-1"} <= {s["id"] for s in yours["items"]} and not any(s["background"] for s in yours["items"])
    assert yours["total"] + bg["total"] == every["total"]
    for page in (every, yours, bg):
        assert page["counts"] == {"all": every["total"], "yours": yours["total"], "background": bg["total"]}
