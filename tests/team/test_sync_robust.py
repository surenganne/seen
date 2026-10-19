"""Sync robustness (2026-10-19 audit): dead letters, ingest validation, throttle, proxy address, redirect guard."""

from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from seen_core import audit, identity, sync
from seen_core.db import ledger_engine
from tests.team.conftest import make_key
from tests.team.test_sync_client import pid, recorded, transport_for  # noqa: F401 - recorded is a fixture
from tests.team.test_team import batch


def status_transport(code: int) -> Any:
    calls = {"n": 0}

    def send(_u: str, _h: dict[str, str], _b: bytes) -> tuple[int, dict[str, Any]]:
        calls["n"] += 1
        return code, {}

    send.calls = calls  # type: ignore[attr-defined]
    return send


def outbox() -> list[tuple[Any, ...]]:
    with ledger_engine().connect() as c:
        return [tuple(r) for r in c.execute(sa.text("select attempts, dead_at, last_status from outbox order by id"))]


@pytest.mark.parametrize("code", [400, 401, 403, 409, 413, 422])
def test_a_permanent_rejection_is_dead_lettered_not_retried_forever(recorded: None, monkeypatch: pytest.MonkeyPatch, code: int) -> None:  # noqa: F811
    monkeypatch.setenv("SEEN_TEAM_API_KEY", "k")
    t = status_transport(code)
    r = sync.push(transport=t)
    assert (r["sent"], r["failed"], r["dead"]) == (0, 0, 1)
    rows = outbox()
    assert len(rows) == 1 and rows[0][1] and rows[0][2] == code
    assert sync.push(transport=t)["dead"] == 0 and t.calls["n"] == 1 and len(outbox()) == 1  # not re-sent, not re-queued
    assert audit.query(type_="sync.batch")[0]["detail"]["ack"] == "rejected"
    with ledger_engine().connect() as c:
        assert c.execute(sa.text("select synced_at from changes")).scalar() is None  # the data is still owed, not lost


@pytest.mark.parametrize("code", [0, 408, 429, 500, 503])
def test_transient_failures_keep_retrying(recorded: None, monkeypatch: pytest.MonkeyPatch, code: int) -> None:  # noqa: F811
    monkeypatch.setenv("SEEN_TEAM_API_KEY", "k")
    r = sync.push(transport=status_transport(code))
    assert (r["sent"], r["failed"], r["dead"]) == (0, 1, 0)
    assert outbox()[0][:2] == (1, None)


def test_retry_failed_revives_dead_batches(recorded: None, team: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setenv("SEEN_TEAM_API_KEY", "wrong")
    assert sync.push(transport=transport_for(team))["dead"] == 1  # 401 from the real server
    monkeypatch.setenv("SEEN_TEAM_API_KEY", make_key(team, pid(), "member", user=identity.user_id()))
    assert sync.push(transport=transport_for(team))["sent"] == 0  # stays parked until you say so
    assert sync.push(transport=transport_for(team), retry_dead=True)["sent"] == 1


# ---- team server ingest
def keyed(team: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_key(team, 'p1', 'member')}", "X-Idempotency-Key": "k1"}


def post(team: TestClient, body: dict) -> int:
    return team.post("/api/sync", json=body, headers=keyed(team)).status_code


def test_negative_counts_are_refused(team: TestClient) -> None:
    for field, value in (("tok_out", -5), ("lines_added", -1), ("cost_usd", -0.5), ("duration_s", -1), ("file_count", -2)):
        b = batch()
        b["changes"][0][field] = value
        assert post(team, b) == 422, field
    b = batch()
    b["changes"][0]["files"] = [{"path": "a.py", "added": -3, "removed": 0}]
    assert post(team, b) == 422


def test_oversized_lists_are_refused(team: TestClient) -> None:
    b = batch()
    b["changes"][0]["files"] = [{"path": f"f{i}.py", "added": 1, "removed": 0} for i in range(501)]
    assert post(team, b) == 422
    b = batch()
    b["changes"][0]["skills"] = [{"skill": f"s{i}"} for i in range(101)]
    assert post(team, b) == 422
    b = batch()
    b["audit_heads"] = [{"at": "t", "seq": i, "hash": "f" * 64} for i in range(1, 102)]
    assert post(team, b) == 422


def test_audit_events_are_validated_not_silently_dropped(team: TestClient) -> None:
    b = batch()
    b["audit"] = [{"nonsense": object.__name__}]
    assert post(team, b) == 422
    good = {"seq": 1, "event_id": "e1", "occurred_at": "t", "actor_kind": "agent", "type": "tool.call", "outcome": "ok",
            "prev_hash": "0" * 64, "hash": "f" * 64, "detail": {"tool": "Edit"}}
    b = batch()
    b["audit"] = [good]
    assert post(team, b) == 200


def test_request_bodies_have_a_size_cap(team: TestClient) -> None:
    h = {**keyed(team), "Content-Type": "application/json"}
    r = team.post("/api/sync", content=b" " * (3 * 1024 * 1024), headers=h)
    assert r.status_code == 413


# ---- throttle and proxy address
def test_successful_requests_count_toward_the_limit(team: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_team import app as team_app

    monkeypatch.setattr(team_app, "MAX_REQUESTS", 6)  # one is spent minting the key
    key = make_key(team, "p1", "lead")
    codes = [team.get("/api/projects", headers={"Authorization": f"Bearer {key}"}).status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and set(codes[5:]) == {429}


def test_behind_a_proxy_clients_are_throttled_separately(team_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_team.app import create_app
    from tests.team.conftest import BOOT

    monkeypatch.setenv("SEEN_TEAM_BOOTSTRAP_KEY", BOOT)
    monkeypatch.setenv("SEEN_TEAM_PROXY_HOPS", "1")
    c = TestClient(create_app(team_url, reset=True), base_url="http://localhost")
    for _ in range(8):  # one noisy client behind the proxy
        assert c.get("/api/projects", headers={"Authorization": "Bearer nope", "X-Forwarded-For": "203.0.113.9"}).status_code == 401
    assert c.get("/api/projects", headers={"Authorization": "Bearer nope", "X-Forwarded-For": "203.0.113.9"}).status_code == 429
    ok = c.get("/api/projects", headers={"Authorization": f"Bearer {BOOT}", "X-Forwarded-For": "198.51.100.7"})
    assert ok.status_code == 200  # a different client is not locked out
