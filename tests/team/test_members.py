"""TD-0: GET /api/projects/{pid}/members lists who syncs, with each person's last sync."""

import sqlalchemy as sa
from fastapi.testclient import TestClient

from tests.team.conftest import admin, make_key
from tests.team.test_sso import bearer, login, sso  # noqa: F401  (sso is a fixture)
from tests.team.test_team import batch


def push(c: TestClient, key: str, user: str, cid: str, idem: str, pid: str = "p1", empty: bool = False) -> None:
    b = batch(pid=pid, cid=cid)
    b["changes"][0]["user_id"] = user
    b["install_id"] = f"inst-{key[-8:]}"
    if empty:
        b["changes"] = []
    r = c.post("/api/sync", json=b, headers={**bearer(key), "X-Idempotency-Key": idem})
    assert r.status_code == 200, r.text


def members(c: TestClient, headers: dict[str, str], pid: str = "p1") -> list[dict]:
    r = c.get(f"/api/projects/{pid}/members", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def sql(url: str, stmt: str, **p: object) -> None:
    e = sa.create_engine(url)
    with e.begin() as cx:
        cx.execute(sa.text(stmt), p)
    e.dispose()


def test_lists_each_member_with_last_synced(team: TestClient, team_url: str) -> None:
    a, b = make_key(team, "p1", "member", "u_a"), make_key(team, "p1", "member", "u_b")
    push(team, a, "u_a", "c1", "i1")
    push(team, a, "u_a", "c2", "i2")
    push(team, b, "u_b", "c3", "i3")
    sql(team_url, "UPDATE team_batches SET received_at='2026-11-01T10:00:00Z' WHERE idempotency_key='i1'")
    sql(team_url, "UPDATE team_batches SET received_at='2026-11-02T10:00:00Z' WHERE idempotency_key='i2'")
    sql(team_url, "UPDATE team_batches SET received_at='2026-11-03T10:00:00Z' WHERE idempotency_key='i3'")
    assert members(team, admin(team)) == [
        {"user_id": "u_a", "email": None, "last_synced_at": "2026-11-02T10:00:00Z", "changes": 2, "key_expired": False},
        {"user_id": "u_b", "email": None, "last_synced_at": "2026-11-03T10:00:00Z", "changes": 1, "key_expired": False}]


def test_synced_with_no_new_changes_still_counts(team: TestClient) -> None:
    a = make_key(team, "p1", "member", "u_a")
    push(team, a, "u_a", "c1", "i1", empty=True)
    m = members(team, admin(team))[0]
    assert m["last_synced_at"] is not None and m["changes"] == 0


def test_never_synced_is_none(team: TestClient) -> None:
    make_key(team, "p1", "member", "u_a")
    assert members(team, admin(team)) == [
        {"user_id": "u_a", "email": None, "last_synced_at": None, "changes": 0, "key_expired": False}]


def test_member_key_is_forbidden(team: TestClient) -> None:
    mk = make_key(team, "p1", "member", "u_a")
    r = team.get("/api/projects/p1/members", headers=bearer(mk))
    assert r.status_code == 403 and r.json()["detail"] == "only leads and admins can list members"
    assert team.get("/api/projects/p1/members", headers=bearer(make_key(team, "p1", "lead"))).status_code == 200
    assert team.get("/api/projects/p1/members", headers=admin(team)).status_code == 200


def test_other_project_is_forbidden(team: TestClient) -> None:
    lead = make_key(team, "pA", "lead")
    assert team.get("/api/projects/pB/members", headers=bearer(lead)).status_code == 403


def test_revoked_and_erased_users_disappear(team: TestClient) -> None:
    make_key(team, "p1", "member", "u_a")
    make_key(team, "p1", "member", "u_b")
    assert [m["user_id"] for m in members(team, admin(team))] == ["u_a", "u_b"]
    assert team.delete("/api/users/u_a", headers=admin(team)).status_code == 200
    assert [m["user_id"] for m in members(team, admin(team))] == ["u_b"]


def test_expired_key_is_flagged(team: TestClient, team_url: str) -> None:
    a = make_key(team, "p1", "member", "u_a")
    push(team, a, "u_a", "c1", "i1")
    sql(team_url, "UPDATE team_api_keys SET expires_at='2020-01-01T00:00:00Z'")
    m = members(team, admin(team))[0]
    assert m["key_expired"] is True and m["last_synced_at"] is not None


def test_sso_user_with_changes_appears_with_email(sso: TestClient) -> None:  # noqa: F811
    ann = login(sso)
    push(sso, ann["key"], "ignored", "c1", "i1")
    m = members(sso, admin(sso))
    assert [(x["user_id"], x["email"], x["changes"], x["key_expired"]) for x in m] == [("sub-ann", "ann@example.com", 1, False)]
    assert m[0]["last_synced_at"] is not None
    assert set(m[0]) == {"user_id", "email", "last_synced_at", "changes", "key_expired"}


def test_sso_member_without_changes_in_project_is_absent(sso: TestClient) -> None:  # noqa: F811
    push(sso, login(sso)["key"], "x", "c1", "i1", pid="p2")
    login(sso, "t-bob")  # logged in, never synced
    assert members(sso, admin(sso), "p1") == []
    assert [m["user_id"] for m in members(sso, admin(sso), "p2")] == ["sub-ann"]


def test_deactivated_and_erased_sso_users_disappear(sso: TestClient) -> None:  # noqa: F811
    push(sso, login(sso)["key"], "x", "c1", "i1")
    push(sso, login(sso, "t-bob")["key"], "x", "c2", "i2")
    assert len(members(sso, admin(sso))) == 2
    sso.put("/api/users/sub-ann", json={"active": False}, headers=admin(sso))
    assert [m["user_id"] for m in members(sso, admin(sso))] == ["sub-bob"]
    sso.delete("/api/users/sub-bob", headers=admin(sso))
    assert members(sso, admin(sso)) == []


def test_sso_lead_lists_any_project_and_sso_member_cannot(sso: TestClient) -> None:  # noqa: F811
    push(sso, login(sso, "t-bob")["key"], "x", "c1", "i1")
    ann = login(sso)
    assert sso.get("/api/projects/p1/members", headers=bearer(ann["key"])).status_code == 403
    sso.put("/api/users/sub-ann", json={"role": "lead"}, headers=admin(sso))
    r = sso.get("/api/projects/p1/members", headers=bearer(login(sso)["key"]))
    assert r.status_code == 200 and [m["user_id"] for m in r.json()] == ["sub-bob"]


def test_manual_and_sso_members_both_listed_once(sso: TestClient) -> None:  # noqa: F811
    push(sso, login(sso)["key"], "x", "c1", "i1")
    make_key(sso, "p1", "member", "u_manual")
    make_key(sso, "p1", "member", "sub-ann")  # a manual key reusing an SSO sub must not double-list
    m = members(sso, admin(sso))
    assert [x["user_id"] for x in m] == ["sub-ann", "u_manual"]
    assert m[0]["email"] == "ann@example.com"


def test_sso_member_with_expired_key_keeps_last_sync(sso: TestClient, team_url: str) -> None:  # noqa: F811
    push(sso, login(sso)["key"], "x", "c1", "i1")
    sql(team_url, "UPDATE team_api_keys SET expires_at='2020-01-01T00:00:00Z'")
    m = members(sso, admin(sso))[0]
    assert m["key_expired"] is True and m["last_synced_at"] is not None
