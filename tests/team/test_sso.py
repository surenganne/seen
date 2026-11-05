"""SSO-1: exchange an IdP identity for a team key; users, roles, deactivation."""

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from seen_team.oidc import Identity, OidcError
from tests.team.conftest import BOOT, admin
from tests.team.test_team import batch

TOKENS = {
    "t-ann": Identity("sub-ann", "Ann@Example.com"),
    "t-bob": Identity("sub-bob", "bob@example.com"),
    "t-boss": Identity("sub-boss", "boss@example.com"),
}


def fake(token: str, nonce: str) -> Identity:
    if token == "boom":
        raise RuntimeError("secret internals")
    if token not in TOKENS or nonce != "n1":
        raise OidcError("invalid token")
    return TOKENS[token]


@pytest.fixture
def sso(team_url: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from seen_team.app import create_app

    monkeypatch.setenv("SEEN_TEAM_BOOTSTRAP_KEY", BOOT)
    monkeypatch.setenv("SEEN_TEAM_ADMINS", "BOSS@example.com, other@example.com")
    return TestClient(create_app(team_url, reset=True, oidc_validate=fake), base_url="http://localhost")


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def login(c: TestClient, tok: str = "t-ann") -> dict:
    r = c.post("/auth/exchange", json={"id_token": tok, "nonce": "n1"})
    assert r.status_code == 200, r.text
    return r.json()


def test_first_login_creates_member(sso: TestClient) -> None:
    r = login(sso)
    assert r["role"] == "member" and r["email"] == "ann@example.com" and r["key"] and r["expires_at"]
    me = sso.get("/auth/me", headers=bearer(r["key"])).json()
    assert me == {"email": "ann@example.com", "role": "member"}
    users = sso.get("/api/users", headers=admin(sso)).json()
    assert users[0]["sub"] == "sub-ann" and users[0]["active"] is True
    assert "key_hash" not in str(sso.get("/api/keys", headers=admin(sso)).json())


def test_admin_email_gets_admin(sso: TestClient) -> None:
    r = login(sso, "t-boss")
    assert r["role"] == "admin"
    assert sso.get("/api/users", headers=bearer(r["key"])).status_code == 200


def test_domain_not_allowed_is_401(sso: TestClient) -> None:
    r = sso.post("/auth/exchange", json={"id_token": "t-evil-token-xyz", "nonce": "n1"})
    assert r.status_code == 401 and "t-evil-token-xyz" not in r.text


def test_exchange_failures_are_rate_limited_and_never_500(sso: TestClient) -> None:
    codes = [sso.post("/auth/exchange", json={"id_token": "boom" if i % 2 else "nope", "nonce": "n1"}).status_code for i in range(12)]
    assert 500 not in codes and set(codes[:8]) == {401} and codes[-1] == 429


def test_deactivated_user_key_stops_immediately(sso: TestClient) -> None:
    r = login(sso)
    assert sso.get("/auth/me", headers=bearer(r["key"])).status_code == 200
    assert sso.put("/api/users/sub-ann", json={"active": False}, headers=admin(sso)).status_code == 200
    assert sso.get("/auth/me", headers=bearer(r["key"])).status_code == 401
    assert sso.post("/auth/exchange", json={"id_token": "t-ann", "nonce": "n1"}).status_code == 401


def test_demotion_applies_to_existing_key(sso: TestClient) -> None:
    r = login(sso, "t-boss")
    assert sso.get("/api/users", headers=bearer(r["key"])).status_code == 200
    assert sso.put("/api/users/sub-boss", json={"role": "member"}, headers=admin(sso)).status_code == 200
    assert sso.get("/api/users", headers=bearer(r["key"])).status_code == 403
    assert sso.get("/auth/me", headers=bearer(r["key"])).json()["role"] == "member"
    # and a later login keeps the stored role, not the admin-email rule
    assert login(sso, "t-boss")["role"] == "member"


def _push(c: TestClient, key: str, pid: str = "p1", user: str | None = "someone-else", idem: str = "i1", cid: str = "c1"):
    b = batch(pid=pid, cid=cid)
    b["changes"][0]["user_id"] = user
    return c.post("/api/sync", json=b, headers={**bearer(key), "X-Idempotency-Key": idem})


def test_sso_lead_reads_all_projects_but_member_does_not(sso: TestClient) -> None:
    member = login(sso, "t-bob")
    assert _push(sso, member["key"]).status_code == 200  # any project, any role
    login(sso)
    sso.put("/api/users/sub-ann", json={"role": "lead"}, headers=admin(sso))
    lead = login(sso)
    assert lead["role"] == "lead"
    assert sso.get("/api/projects/p1/overview", headers=bearer(lead["key"])).status_code == 200
    assert [p["id"] for p in sso.get("/api/projects", headers=bearer(lead["key"])).json()] == ["p1"]
    assert sso.get("/api/projects/p1/overview", headers=bearer(member["key"])).status_code == 403


def test_manual_lead_without_project_still_sees_nothing(sso: TestClient) -> None:
    assert _push(sso, login(sso, "t-bob")["key"]).status_code == 200
    k = sso.post("/api/keys", json={"project_id": None, "role": "lead"}, headers=admin(sso)).json()["key"]
    assert sso.get("/api/projects/p1/overview", headers=bearer(k)).status_code == 403
    assert sso.get("/api/projects", headers=bearer(k)).json() == []


def test_sync_overrides_user_id_for_sso_keys(sso: TestClient, team_url: str) -> None:
    k = login(sso, "t-bob")["key"]
    assert _push(sso, k, user="forged").status_code == 200
    assert _push(sso, k, user=None, idem="i2", cid="c2").status_code == 200
    e = sa.create_engine(team_url)
    with e.connect() as c:
        assert {r[0] for r in c.execute(sa.text("select user_id from team_changes"))} == {"sub-bob"}
        assert all("forged" not in str(r[0]) for r in c.execute(sa.text("select payload from team_changes")))
    # manual member keys keep the 403 on a mismatch
    m = sso.post("/api/keys", json={"project_id": "p1", "role": "member", "user_id": "u_a"}, headers=admin(sso)).json()["key"]
    assert _push(sso, m, user="forged", idem="i3", cid="c3").status_code == 403


def test_sso_relogin_key_can_continue_same_install(sso: TestClient) -> None:
    assert _push(sso, login(sso, "t-bob")["key"]).status_code == 200
    assert _push(sso, login(sso, "t-bob")["key"], idem="i2").status_code == 200  # same install id, same change id, new key


def test_bootstrap_disabled(team_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_team.app import create_app

    monkeypatch.setenv("SEEN_TEAM_BOOTSTRAP_KEY", BOOT)
    monkeypatch.setenv("SEEN_TEAM_BOOTSTRAP_DISABLE", "1")
    c = TestClient(create_app(team_url, reset=True, oidc_validate=fake), base_url="http://localhost")
    assert c.get("/api/keys", headers=admin(c)).status_code == 401


def test_production_refuses_to_start_without_oidc_config(team_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_team.app import create_app

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SEEN_TEAM_BOOTSTRAP_KEY", BOOT)
    for v in ("SEEN_OIDC_ISSUER", "SEEN_OIDC_CLIENT_ID", "SEEN_TEAM_BOOTSTRAP_DISABLE"):
        monkeypatch.delenv(v, raising=False)
    create_app(team_url, reset=True)  # bootstrap-only auth stays allowed
    monkeypatch.setenv("SEEN_TEAM_BOOTSTRAP_DISABLE", "1")
    with pytest.raises(SystemExit):
        create_app(team_url, reset=True)  # no way to authenticate at all
    create_app(team_url, reset=True, oidc_validate=fake)


def test_partial_oidc_config_stops_startup(team_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_team.app import create_app
    from seen_team.oidc import OidcConfigError

    monkeypatch.setenv("SEEN_OIDC_ISSUER", "https://login.microsoftonline.com/common/v2.0")
    monkeypatch.setenv("SEEN_OIDC_CLIENT_ID", "cid")
    with pytest.raises(OidcConfigError):
        create_app(team_url, reset=True)


def test_users_routes_are_admin_only(sso: TestClient) -> None:
    m = login(sso)["key"]
    assert sso.get("/api/users", headers=bearer(m)).status_code == 403
    assert sso.put("/api/users/sub-ann", json={"role": "admin"}, headers=bearer(m)).status_code == 403
    assert sso.get("/api/users").status_code == 401
    assert sso.put("/api/users/nobody", json={"active": False}, headers=admin(sso)).status_code == 404
    assert sso.put("/api/users/sub-ann", json={"role": "root"}, headers=admin(sso)).status_code == 422
    assert sso.get("/auth/me").status_code == 401


def test_erase_user_also_revokes_sso_keys(sso: TestClient) -> None:
    k = login(sso, "t-bob")["key"]
    assert _push(sso, k).status_code == 200
    r = sso.delete("/api/users/sub-bob", headers=admin(sso))
    assert r.json()["changes"] == 1 and r.json()["keys_revoked"] == 1
    assert sso.get("/auth/me", headers=bearer(k)).status_code == 401
    assert all(u["sub"] != "sub-bob" for u in sso.get("/api/users", headers=admin(sso)).json())  # email erased too


def test_auth_config_without_real_config_is_503(sso: TestClient) -> None:
    r = sso.get("/auth/config")
    assert r.status_code == 503 and "not configured" in r.json()["detail"]


def test_auth_config_returns_only_three_fields(team_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_team import app as appmod

    iss = "https://login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0"
    monkeypatch.setenv("SEEN_OIDC_ISSUER", iss)
    monkeypatch.setenv("SEEN_OIDC_CLIENT_ID", "cid")
    monkeypatch.setenv("SEEN_OIDC_ALLOWED_DOMAINS", "example.com")
    disc = {"authorization_endpoint": "https://a", "token_endpoint": "https://t", "jwks_uri": "https://j", "issuer": iss}
    monkeypatch.setattr(appmod, "_get_json", lambda u: disc)
    c = TestClient(appmod.create_app(team_url, reset=True), base_url="http://localhost")
    assert c.get("/auth/config").json() == {"authorization_endpoint": "https://a", "token_endpoint": "https://t", "client_id": "cid"}
    monkeypatch.setattr(appmod, "_get_json", lambda u: (_ for _ in ()).throw(OSError("net")))
    c2 = TestClient(appmod.create_app(team_url, reset=True), base_url="http://localhost")
    assert c2.get("/auth/config").status_code == 503


def test_old_database_gets_origin_column(tmp_path) -> None:
    from seen_team.app import create_app

    url = f"sqlite:///{tmp_path / 'old.db'}"
    e = sa.create_engine(url)
    with e.begin() as c:
        c.execute(sa.text("create table team_api_keys (id varchar(32) primary key, key_hash varchar(64), project_id varchar(64), "
                          "role varchar(16), user_id varchar(80), created_at varchar(40))"))
        c.execute(sa.text("insert into team_api_keys values ('k','h',null,'admin',null,'x')"))
    create_app(url)
    with e.connect() as c:
        assert c.execute(sa.text("select origin from team_api_keys")).scalar() == "manual"
