"""SSO-1: exchange an IdP identity for a team key; users, roles, deactivation."""

import itertools
import threading

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
    "t-other": Identity("sub-other", "other@example.com"),
}


def fake(token: str, nonce: str) -> Identity:
    token = token.split("#")[0]  # "#n" makes a distinct id_token for the same person: each real token is single-use
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


_seq = itertools.count()


def login(c: TestClient, tok: str = "t-ann") -> dict:
    r = c.post("/auth/exchange", json={"id_token": f"{tok}#{next(_seq)}", "nonce": "n1"})
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


def test_validator_rejection_is_fixed_401_without_echo(sso: TestClient) -> None:
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
    login(sso, "t-other")  # a second admin, so the demotion is allowed
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
    tomb = [u for u in sso.get("/api/users", headers=admin(sso)).json() if u["sub"] == "sub-bob"]
    assert tomb and tomb[0]["email"] == "" and tomb[0]["active"] is False  # tombstone: email erased, re-entry needs re-activation


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


def test_erase_does_not_undo_deactivation(sso: TestClient) -> None:
    for tok in ("t-bob", "t-ann"):
        login(sso, tok)
    sso.put("/api/users/sub-bob", json={"active": False}, headers=admin(sso))
    for sub, tok in (("sub-bob", "t-bob"), ("sub-ann", "t-ann")):  # one deactivated, one active
        assert sso.delete(f"/api/users/{sub}", headers=admin(sso)).status_code == 200
        assert sso.post("/auth/exchange", json={"id_token": tok, "nonce": "n1"}).status_code == 401
    assert sso.put("/api/users/sub-ann", json={"active": True}, headers=admin(sso)).status_code == 200
    assert login(sso, "t-ann")["email"] == "ann@example.com"


def test_re_logged_in_user_reads_own_anchors_but_others_cannot(sso: TestClient) -> None:
    assert _push(sso, login(sso, "t-bob")["key"]).status_code == 200
    assert sso.get("/api/anchors/inst-1", headers=bearer(login(sso, "t-bob")["key"])).status_code == 200
    assert sso.get("/api/anchors/inst-1", headers=bearer(login(sso, "t-ann")["key"])).status_code == 403


def test_other_sso_user_cannot_take_install_or_change(sso: TestClient) -> None:
    assert _push(sso, login(sso, "t-bob")["key"]).status_code == 200
    ann = login(sso, "t-ann")["key"]
    assert _push(sso, ann, idem="a1").status_code == 403  # same install
    b = batch()
    b["install_id"] = "inst-2"
    r = sso.post("/api/sync", json=b, headers={**bearer(ann), "X-Idempotency-Key": "a2"})
    assert r.status_code == 409  # same change id, new install


def test_last_admin_cannot_be_removed(sso: TestClient) -> None:
    login(sso, "t-boss")
    for body in ({"role": "member"}, {"active": False}):
        r = sso.put("/api/users/sub-boss", json=body, headers=admin(sso))
        assert r.status_code == 409 and "last" in r.json()["detail"]
    login(sso, "t-ann")
    assert sso.put("/api/users/sub-ann", json={"role": "admin"}, headers=admin(sso)).status_code == 200
    assert sso.put("/api/users/sub-boss", json={"role": "member"}, headers=admin(sso)).status_code == 200
    assert sso.put("/api/users/sub-ann", json={"active": False}, headers=admin(sso)).status_code == 409


def test_list_keys_shows_origin_and_live_role(sso: TestClient) -> None:
    login(sso, "t-boss")
    login(sso, "t-ann")
    sso.put("/api/users/sub-ann", json={"role": "lead"}, headers=admin(sso))
    sso.put("/api/users/sub-ann", json={"role": "member"}, headers=admin(sso))
    rows = {r["user_id"]: r for r in sso.get("/api/keys", headers=admin(sso)).json()}
    assert rows["sub-ann"]["origin"] == "sso" and rows["sub-ann"]["role"] == "member"
    sso.put("/api/users/sub-ann", json={"role": "lead"}, headers=admin(sso))
    assert {r["user_id"]: r for r in sso.get("/api/keys", headers=admin(sso)).json()}["sub-ann"]["role"] == "lead"


def test_malformed_exchange_body_does_not_echo_token(sso: TestClient) -> None:
    r = sso.post("/auth/exchange", json={"id_token": "SECRET-TOKEN-VALUE", "nonce": "n1", "extra": "SECRET-EXTRA"})
    assert r.status_code == 422 and "SECRET" not in r.text
    r = sso.post("/auth/exchange", json={"id_token": 12345678, "nonce": ["SECRET-N"]})
    assert r.status_code == 422 and "SECRET" not in r.text and "12345678" not in r.text


def test_auth_config_invalid_discovery_is_503_and_not_cached(team_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_team import app as appmod

    monkeypatch.setenv("SEEN_OIDC_ISSUER", "https://login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0")
    monkeypatch.setenv("SEEN_OIDC_CLIENT_ID", "cid")
    monkeypatch.setenv("SEEN_OIDC_ALLOWED_DOMAINS", "example.com")
    bad = {"authorization_endpoint": "http://a", "token_endpoint": "https://t"}
    good = {"authorization_endpoint": "https://a", "token_endpoint": "https://t"}
    cur = [bad]
    monkeypatch.setattr(appmod, "_get_json", lambda u: cur[0])
    c = TestClient(appmod.create_app(team_url, reset=True), base_url="http://localhost")
    assert c.get("/auth/config").status_code == 503
    cur[0] = good
    assert c.get("/auth/config").status_code == 200  # the bad document was not cached


def test_non_ascii_email_refused_before_admin_match(team_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_team.app import create_app

    monkeypatch.setenv("SEEN_TEAM_BOOTSTRAP_KEY", BOOT)
    monkeypatch.setenv("SEEN_TEAM_ADMINS", "kim@example.com")
    v = lambda tok, n: Identity("sub-k", "\u212Aim@example.com")  # noqa: E731 - Kelvin sign lowercases to "k"
    c = TestClient(create_app(team_url, reset=True, oidc_validate=v), base_url="http://localhost")
    r = c.post("/auth/exchange", json={"id_token": "x", "nonce": "n1"})
    assert r.status_code == 401 and r.json() == {"detail": "sign-in failed"}
    assert c.get("/api/users", headers=admin(c)).json() == []


@pytest.mark.parametrize("val", ["1", "true", "YES", "True"])
def test_bootstrap_disable_spellings(team_url: str, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
    from seen_team.app import create_app

    monkeypatch.setenv("SEEN_TEAM_BOOTSTRAP_KEY", BOOT)
    monkeypatch.setenv("SEEN_TEAM_BOOTSTRAP_DISABLE", val)
    c = TestClient(create_app(team_url, reset=True, oidc_validate=fake), base_url="http://localhost")
    assert c.get("/api/keys", headers=admin(c)).status_code == 401


def test_simultaneous_first_login_is_not_a_401(sso: TestClient, team_url: str) -> None:
    from sqlalchemy import event

    from seen_team.models import TeamUser

    e2 = sa.create_engine(team_url)
    fired: list[int] = []

    def racer(mapper, conn, target):  # type: ignore[no-untyped-def]
        if not fired:  # another request wins the insert just before ours
            fired.append(1)
            with e2.begin() as c:
                c.execute(sa.text("insert into team_users (sub,email,role,active,first_seen,last_login) values "
                                  "('sub-ann','ann@example.com','member',1,'t','t')"))

    event.listen(TeamUser, "before_insert", racer)
    try:
        assert login(sso)["role"] == "member"
    finally:
        event.remove(TeamUser, "before_insert", racer)
    assert fired


def test_delete_me_revokes_only_the_calling_sso_key(sso: TestClient) -> None:
    a1, a2 = login(sso)["key"], login(sso)["key"]
    b = login(sso, "t-bob")["key"]
    assert sso.delete("/auth/me", headers=bearer(a1)).status_code == 204
    assert sso.get("/auth/me", headers=bearer(a1)).status_code == 401
    assert sso.delete("/auth/me", headers=bearer(a1)).status_code == 401  # already dead: same as any wrong key
    assert sso.get("/auth/me", headers=bearer(a2)).status_code == 200
    assert sso.get("/auth/me", headers=bearer(b)).status_code == 200


def test_delete_me_refuses_manual_and_bootstrap_keys(sso: TestClient) -> None:
    from tests.team.conftest import make_key

    m = make_key(sso, "p1", "member")
    r = sso.delete("/auth/me", headers=bearer(m))
    assert r.status_code == 403 and "revoke" in r.text
    assert sso.get("/auth/me", headers=bearer(m)).status_code == 200
    assert sso.delete("/auth/me", headers=admin(sso)).status_code == 403


def test_erase_refuses_the_last_active_admin(sso: TestClient) -> None:
    boss = bearer(login(sso, "t-boss")["key"])
    r = sso.delete("/api/users/sub-boss", headers=boss)
    assert r.status_code == 409 and r.json()["detail"] == "cannot remove the last active admin"
    assert login(sso, "t-other")["role"] == "admin"
    assert sso.delete("/api/users/sub-boss", headers=bearer(login(sso, "t-other")["key"])).status_code == 200


def _sso_key_count(c: TestClient) -> int:
    return sum(1 for k in c.get("/api/keys", headers=admin(c)).json() if k["origin"] == "sso")


def test_id_token_replay_mints_one_key(sso: TestClient) -> None:
    body = {"id_token": "t-ann#replay", "nonce": "n1"}
    assert sso.post("/auth/exchange", json=body).status_code == 200
    r = sso.post("/auth/exchange", json=body)
    assert r.status_code == 401 and r.json() == {"detail": "sign-in failed"}
    assert _sso_key_count(sso) == 1
    assert sso.post("/auth/exchange", json={"id_token": "t-ann#other", "nonce": "n1"}).status_code == 200  # a new token is fine
    assert _sso_key_count(sso) == 2


def test_id_token_replay_counts_as_a_failure_for_the_limiter(sso: TestClient) -> None:
    body = {"id_token": "t-ann#r", "nonce": "n1"}
    assert sso.post("/auth/exchange", json=body).status_code == 200
    codes = [sso.post("/auth/exchange", json=body).status_code for _ in range(10)]
    assert codes[:8] == [401] * 8 and codes[-1] == 429


def test_used_tokens_expire_and_are_pruned(sso: TestClient, team_url: str) -> None:
    e = sa.create_engine(team_url)
    with e.begin() as c:
        c.execute(sa.text("insert into team_used_tokens (token_hash, expires_at) values ('old', '2000-01-01T00:00:00Z')"))
        c.execute(sa.text("insert into team_used_tokens (token_hash, expires_at) values ('live', '2999-01-01T00:00:00Z')"))
    login(sso)
    with e.begin() as c:
        left = {r[0] for r in c.execute(sa.text("select token_hash from team_used_tokens"))}
    assert "old" not in left and "live" in left and len(left) == 2  # the live row and the token just exchanged


def _race(c: TestClient, i: int) -> list[int]:
    gate, out = threading.Barrier(2), []

    def go() -> None:
        gate.wait()
        out.append(c.post("/auth/exchange", json={"id_token": f"t-bob#race{i}", "nonce": "n1"}).status_code)

    ts = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return sorted(out)


def test_concurrent_double_submit_mints_at_most_one_key(sso: TestClient) -> None:
    for i in range(5):
        out = _race(sso, i)
        assert out[0] == 200 and out.count(200) == 1, out
    assert _sso_key_count(sso) == 5


def _manual_key_for(c: TestClient, sub: str) -> str:
    return c.post("/api/keys", json={"project_id": "p1", "role": "member", "user_id": sub}, headers=admin(c)).json()["key"]


def test_deactivate_revokes_manual_keys_bound_to_the_same_user_id(sso: TestClient) -> None:
    login(sso)
    manual = _manual_key_for(sso, "sub-ann")
    assert _push(sso, manual, user="sub-ann").status_code == 200
    assert sso.put("/api/users/sub-ann", json={"active": False}, headers=admin(sso)).status_code == 200
    assert _push(sso, manual, user="sub-ann", idem="i2", cid="c2").status_code == 401  # at once
    assert sso.put("/api/users/sub-ann", json={"active": True}, headers=admin(sso)).status_code == 200
    assert _push(sso, manual, user="sub-ann", idem="i3", cid="c3").status_code == 401  # reactivation does not un-revoke
    assert sso.post("/auth/exchange", json={"id_token": "t-ann#again", "nonce": "n1"}).status_code == 200  # a new login does


def test_role_change_alone_does_not_revoke_manual_keys(sso: TestClient) -> None:
    login(sso)
    manual = _manual_key_for(sso, "sub-ann")
    sso.put("/api/users/sub-ann", json={"role": "lead"}, headers=admin(sso))
    assert _push(sso, manual, user="sub-ann").status_code == 200


def test_erase_revokes_manual_keys_bound_to_the_same_user_id(sso: TestClient) -> None:
    login(sso)
    manual = _manual_key_for(sso, "sub-ann")
    assert sso.delete("/api/users/sub-ann", headers=admin(sso)).json()["keys_revoked"] == 2
    assert _push(sso, manual, user="sub-ann").status_code == 401


def test_production_refuses_a_plain_http_issuer(team_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from seen_team.app import create_app

    monkeypatch.setenv("SEEN_TEAM_BOOTSTRAP_KEY", BOOT)
    monkeypatch.setenv("SEEN_OIDC_ISSUER", "http://localhost:9/t1/v2.0")
    monkeypatch.setenv("SEEN_OIDC_CLIENT_ID", "cid")
    monkeypatch.setenv("SEEN_OIDC_ALLOWED_DOMAINS", "example.com")
    monkeypatch.setenv("APP_ENV", "test")
    create_app(team_url, reset=True)  # dev and tests may use a loopback http IdP
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(SystemExit) as e:
        create_app(team_url, reset=True)
    assert str(e.value) == "SEEN_OIDC_ISSUER must be https in production."
