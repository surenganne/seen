"""Key lifecycle and erasure (DPDP): list, revoke, expire, delete a person, delete a project."""

import sqlalchemy as sa
from fastapi.testclient import TestClient

from tests.team.conftest import admin, make_key
from tests.team.test_team import batch


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def send(team: TestClient, key: str, cid: str = "c1", pid: str = "p1", idem: str = "i1") -> None:
    r = team.post("/api/sync", json=batch(pid=pid, cid=cid), headers={**bearer(key), "X-Idempotency-Key": idem})
    assert r.status_code == 200, r.text


def test_list_keys_is_admin_only_and_never_shows_secrets(team: TestClient) -> None:
    member = make_key(team, "p1", "member")
    assert team.get("/api/keys", headers=bearer(member)).status_code == 403
    rows = team.get("/api/keys", headers=admin(team)).json()
    assert len(rows) == 1 and rows[0]["role"] == "member" and rows[0]["revoked_at"] is None
    assert "key_hash" not in rows[0] and member not in str(rows)


def test_revoked_key_stops_working(team: TestClient) -> None:
    member = make_key(team, "p1", "member")
    kid = team.get("/api/keys", headers=admin(team)).json()[0]["id"]
    assert team.delete(f"/api/keys/{kid}", headers=bearer(member)).status_code == 403
    assert team.delete(f"/api/keys/{kid}", headers=admin(team)).status_code == 200
    assert team.get("/api/projects", headers=bearer(member)).status_code == 401
    assert team.get("/api/keys", headers=admin(team)).json()[0]["revoked_at"]
    assert team.delete("/api/keys/nope", headers=admin(team)).status_code == 404


def test_expired_key_is_refused(team: TestClient, team_url: str) -> None:
    r = team.post("/api/keys", json={"project_id": "p1", "role": "lead", "expires_in_days": 30}, headers=admin(team))
    key = r.json()["key"]
    assert team.get("/api/projects", headers=bearer(key)).status_code == 200
    assert team.get("/api/keys", headers=admin(team)).json()[0]["expires_at"]
    with sa.create_engine(team_url).begin() as c:
        c.execute(sa.text("update team_api_keys set expires_at='2000-01-01T00:00:00Z'"))
    assert team.get("/api/projects", headers=bearer(key)).status_code == 401


def test_delete_user_erases_their_changes_and_revokes_their_keys(team: TestClient) -> None:
    a = make_key(team, "p1", "member", "u_a")
    send(team, a)
    lead = make_key(team, "p1", "lead")
    assert team.delete("/api/users/u_a", headers=bearer(lead)).status_code == 403
    res = team.delete("/api/users/u_a", headers=admin(team)).json()
    assert res["changes"] == 1 and res["keys_revoked"] == 1
    assert team.get("/api/projects", headers=bearer(a)).status_code == 401
    assert team.get("/api/projects", headers=admin(team)).json()[0]["changes"] == 0


def test_delete_project_erases_its_changes(team: TestClient) -> None:
    a = make_key(team, "p1", "member")
    send(team, a)
    assert team.delete("/api/projects/p1", headers=bearer(a)).status_code == 403
    assert team.delete("/api/projects/p1", headers=admin(team)).json()["changes"] == 1
    assert team.get("/api/projects", headers=admin(team)).json() == []


def test_database_from_before_key_expiry_is_upgraded_in_place(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from seen_team.app import create_app

    url = f"sqlite:///{tmp_path / 'old.db'}"
    with sa.create_engine(url).begin() as c:
        c.execute(sa.text("create table team_api_keys(id varchar(32) primary key, key_hash varchar(64) unique, project_id varchar(64),"
                          " role varchar(16), user_id varchar(80), created_at varchar(40))"))
        c.execute(sa.text("insert into team_api_keys values('k1','h','p1','lead',null,'2026-01-01T00:00:00Z')"))
    monkeypatch.setenv("SEEN_TEAM_BOOTSTRAP_KEY", "boot-" + "k" * 40)
    client = TestClient(create_app(url), base_url="http://localhost")
    rows = client.get("/api/keys", headers=admin(client)).json()
    assert rows[0]["id"] == "k1" and rows[0]["revoked_at"] is None
