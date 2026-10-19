import pytest
from fastapi.testclient import TestClient

from tests.team.conftest import BOOT, admin, make_key


def batch(pid: str = "p1", cid: str = "c1", cost: float = 0.5) -> dict:
    return {"changes": [{"id": cid, "project_id": pid, "session_id": "s1", "seq": 1, "started_at": "2026-10-18T10:00:00Z",
                         "duration_s": 30, "tool": "claude-code", "user_id": "u_a", "model": "claude-sonnet-5-5", "git_status": "committed",
                         "mem_state": "loaded", "file_count": 2, "lines_added": 10, "lines_removed": 3, "tok_in": 5, "tok_out": 900,
                         "tok_cache_read": 1000, "tok_cache_write": 100, "cost_usd": cost, "price_version": "v1",
                         "skills": [{"skill": "tdd", "kind": "plugin", "hash": "a" * 64, "trigger": "model", "status": "approved"}],
                         "policies": [{"policy": "p1:pol", "met": False}], "pii": {"state": "found", "counts": {"email": 2}}}],
            "audit_heads": [{"at": "2026-10-18T10:05:00Z", "seq": 42, "hash": "f" * 64}], "audit": [], "install_id": "inst-1"}


def test_sync_requires_key_and_is_idempotent(team: TestClient) -> None:
    key = make_key(team, "p1", "member")
    h = {"Authorization": f"Bearer {key}", "X-Idempotency-Key": "batch-1"}
    assert team.post("/api/sync", json=batch()).status_code == 401
    r = team.post("/api/sync", json=batch(), headers=h).json()
    assert r == {"accepted": 1, "duplicate": False, "anchored": {"seq": 42, "hash": "f" * 64}}
    again = team.post("/api/sync", json=batch(), headers=h).json()
    assert again["duplicate"] is True
    assert team.post("/api/sync", json=batch(cost=0.9), headers={**h, "X-Idempotency-Key": "batch-2"}).json()["accepted"] == 1


def test_key_scoped_to_project(team: TestClient) -> None:
    key = make_key(team, "p1", "member")
    h = {"Authorization": f"Bearer {key}", "X-Idempotency-Key": "b"}
    assert team.post("/api/sync", json=batch(pid="p2"), headers=h).status_code == 403


def test_read_api_same_shapes_and_roles(team: TestClient) -> None:
    w = make_key(team, "p1", "member")
    team.post("/api/sync", json=batch(), headers={"Authorization": f"Bearer {w}", "X-Idempotency-Key": "x"})
    lead = make_key(team, "p1", "lead")
    projects = team.get("/api/projects", headers={"Authorization": f"Bearer {lead}"}).json()
    assert projects[0]["id"] == "p1" and projects[0]["changes"] == 1
    o = team.get("/api/projects/p1/overview", params={"range": 28}, headers={"Authorization": f"Bearer {lead}"}).json()
    assert o["tiles"]["changes"] == 1 and o["tiles"]["pii_changes"] == 1 and o["top_skills"][0]["skill_id"] == "tdd"
    other = make_key(team, "p2", "lead")
    assert team.get("/api/projects/p1/overview", headers={"Authorization": f"Bearer {other}"}).status_code == 403
    assert len(team.get("/api/projects", headers=admin(team)).json()) == 1


def test_member_sees_only_own_detail(team: TestClient) -> None:
    w = make_key(team, "p1", "member")
    team.post("/api/sync", json=batch(), headers={"Authorization": f"Bearer {w}", "X-Idempotency-Key": "x"})
    lead = make_key(team, "p1", "lead")
    assert team.get("/api/projects/p1/changes", headers={"Authorization": f"Bearer {lead}"}).status_code == 403  # per-person detail is private
    mine = team.get("/api/projects/p1/changes", params={"user_id": "u_a"}, headers={"Authorization": f"Bearer {w}"})
    assert mine.status_code == 200


def test_anchor_lookup(team: TestClient) -> None:
    w = make_key(team, "p1", "member")
    team.post("/api/sync", json=batch(), headers={"Authorization": f"Bearer {w}", "X-Idempotency-Key": "x"})
    a = team.get("/api/anchors/inst-1", headers={"Authorization": f"Bearer {w}"}).json()
    assert a["seq"] == 42 and a["hash"] == "f" * 64 and a["at"]


def test_never_accepts_content_fields(team: TestClient) -> None:
    w = make_key(team, "p1", "member")
    b = batch()
    b["changes"][0]["prompt_text"] = "secret prompt"
    b["changes"][0]["summary"] = "x"
    r = team.post("/api/sync", json=b, headers={"Authorization": f"Bearer {w}", "X-Idempotency-Key": "y"})
    assert r.status_code == 422


def test_failed_auth_throttled_per_ip(team: TestClient) -> None:
    for _ in range(10):
        team.get("/api/projects", headers={"Authorization": "Bearer wrong"})
    assert team.get("/api/projects", headers=admin(team)).status_code == 429


def test_production_refuses_short_bootstrap_key(team_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_team.app import create_app

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SEEN_TEAM_BOOTSTRAP_KEY", "short")
    with pytest.raises(SystemExit):
        create_app(team_url, reset=True)
    monkeypatch.setenv("SEEN_TEAM_BOOTSTRAP_KEY", BOOT)
    create_app(team_url, reset=True)


def test_keys_stored_hashed(team: TestClient, team_url: str) -> None:
    import sqlalchemy as sa

    key = make_key(team, "p1", "member")
    with sa.create_engine(team_url).connect() as c:
        stored = [r[0] for r in c.execute(sa.text("select key_hash from team_api_keys"))]
    assert key not in stored and all(len(h) == 64 for h in stored)


def test_security_headers_and_non_ascii_token(team: TestClient) -> None:
    r = team.get("/api/projects", headers={"Authorization": "Bearer ключ".encode()})
    assert r.status_code == 401  # non-ASCII token must not 500 (compare_digest on bytes)
    assert r.headers["x-frame-options"] == "DENY"


def test_member_key_requires_user_and_detail_is_own_only(team: TestClient) -> None:
    assert team.post("/api/keys", json={"project_id": "p1", "role": "member"}, headers=admin(team)).status_code == 422
    a = make_key(team, "p1", "member", user="u_a")
    team.post("/api/sync", json=batch(), headers={"Authorization": f"Bearer {a}", "X-Idempotency-Key": "1"})
    b = make_key(team, "p1", "member", user="u_b")
    got = team.get("/api/projects/p1/changes", params={"user_id": "u_a"}, headers={"Authorization": f"Bearer {b}"})
    assert got.status_code == 403
    mine = team.get("/api/projects/p1/changes", headers={"Authorization": f"Bearer {a}"}).json()
    assert [c["id"] for c in mine] == ["c1"]


def test_member_cannot_write_as_someone_else(team: TestClient) -> None:
    b = make_key(team, "p1", "member", user="u_b")
    r = team.post("/api/sync", json=batch(), headers={"Authorization": f"Bearer {b}", "X-Idempotency-Key": "1"})  # payload says u_a
    assert r.status_code == 403


def test_install_bound_to_first_key_and_anchors_append_only(team: TestClient) -> None:
    a = make_key(team, "p1", "member", user="u_a")
    h = {"Authorization": f"Bearer {a}"}
    team.post("/api/sync", json=batch(), headers={**h, "X-Idempotency-Key": "1"})
    other = make_key(team, "p1", "member", user="u_c")
    b = batch()
    b["changes"] = []
    assert team.post("/api/sync", json=b, headers={"Authorization": f"Bearer {other}", "X-Idempotency-Key": "2"}).status_code == 403
    forged = batch()
    forged["changes"] = []
    forged["audit_heads"] = [{"at": "x", "seq": 42, "hash": "e" * 64}]
    assert team.post("/api/sync", json=forged, headers={**h, "X-Idempotency-Key": "3"}).status_code == 409
    assert team.get("/api/anchors/inst-1", headers={"Authorization": f"Bearer {other}"}).status_code == 403
    assert team.get("/api/anchors/inst-1", headers=h).json()["hash"] == "f" * 64


def test_change_ids_cannot_be_overwritten_across_projects_or_writers(team: TestClient) -> None:
    a = make_key(team, "p1", "member", user="u_a")
    team.post("/api/sync", json=batch(), headers={"Authorization": f"Bearer {a}", "X-Idempotency-Key": "1"})
    p2 = make_key(team, "p2", "member", user="u_a")
    b = batch(pid="p2")
    b["install_id"] = "inst-2"
    assert team.post("/api/sync", json=b, headers={"Authorization": f"Bearer {p2}", "X-Idempotency-Key": "1"}).status_code == 409


@pytest.mark.parametrize("role", ["lead", "admin"])
def test_only_member_keys_write(team: TestClient, role: str) -> None:
    k = make_key(team, "p1" if role == "lead" else None, role)
    r = team.post("/api/sync", json=batch(), headers={"Authorization": f"Bearer {k}", "X-Idempotency-Key": "z"})
    assert r.status_code == 403
    assert team.post("/api/sync", json=batch(), headers={**admin(team), "X-Idempotency-Key": "b"}).status_code == 403
