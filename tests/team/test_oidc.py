import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from seen_team.oidc import (
    Identity,
    OidcConfig,
    OidcConfigError,
    OidcError,
    make_jwks_fetcher,
    validate_id_token,
)

TENANT = "11111111-2222-3333-4444-555555555555"
ISS = f"https://login.microsoftonline.com/{TENANT}/v2.0"
CID = "client-1"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CFG = OidcConfig(ISS, CID, frozenset({"example.com"}))


def jwk(key: Any, kid: str = "k1") -> dict:
    d = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    return {**d, "kid": kid, "use": "sig", "alg": "RS256"}


def jwks_of(*keys: dict):
    calls: list[bool] = []

    def f(refresh: bool) -> dict:
        calls.append(refresh)
        return {"keys": list(keys)}

    f.calls = calls  # type: ignore[attr-defined]
    return f


json_null = object()


def tok(key: Any = KEY, kid: str = "k1", alg: str = "RS256", **over: Any) -> str:
    now = int(time.time())
    claims = {"iss": ISS, "aud": CID, "sub": "sub-1", "iat": now, "exp": now + 600,
              "nonce": "n1", "email": "a@example.com", "tid": TENANT, **over}
    claims = {k: (None if v is json_null else v) for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


def check(token: str, jwks=None, nonce: str = "n1") -> Identity:
    return validate_id_token(token, nonce, CFG, jwks or jwks_of(jwk(KEY)))


def bad(token: str, **kw: Any) -> None:
    with pytest.raises(OidcError) as e:
        check(token, **kw)
    assert str(e.value) == "invalid token"


def test_valid_token():
    assert check(tok()) == Identity("sub-1", "a@example.com")


def test_email_normalised_lowercase():
    assert check(tok(email="A@Example.COM")).email == "a@example.com"


def test_rejects_alg_none_and_hs256_confusion():
    bad(tok(key=None, alg="none"))
    now = int(time.time())
    hs = jwt.encode({"iss": ISS, "aud": CID, "sub": "s", "iat": now, "exp": now + 60, "nonce": "n1",
                     "email": "a@example.com"}, "x" * 40, algorithm="HS256", headers={"kid": "k1"})
    bad(hs)


def test_bad_signature():
    bad(tok(key=OTHER))


def test_wrong_issuer():
    bad(tok(iss="https://evil.example/v2.0"))


def test_wrong_audience():
    bad(tok(aud="someone-else"))


def test_expired_and_not_yet_valid():
    now = int(time.time())
    bad(tok(exp=now - 3600, iat=now - 7200))
    bad(tok(nbf=now + 3600))
    bad(tok(iat=now + 3600, exp=now + 7200))


def test_missing_required_claims():
    bad(tok(exp=None))
    bad(tok(iat=None))
    bad(tok(sub=None))


def test_nonce_mismatch():
    bad(tok(nonce="other"))
    bad(tok(nonce=None))
    bad(tok(), nonce="")


@pytest.mark.parametrize("email", [
    "a@evil-example.com", "a@example.com.evil.io", "a@@example.com", "a@x@example.com",
    "example.com", "a@", "a@sub.example.com", "", 5,
])
def test_email_domain_exact_match_rejects(email):
    bad(tok(email=email))


def test_email_missing_rejected():
    bad(tok(email=None))


def test_unverified_email_rejected_when_claim_present():
    bad(tok(email_verified=False))
    bad(tok(email_verified="false"))
    bad(tok(email_verified="true"))
    bad(tok(email_verified=1))
    bad(tok(email_verified=json_null))
    assert check(tok(email_verified=True)).email == "a@example.com"


def test_email_verified_absent_accepted_for_pinned_issuer():
    assert "email_verified" not in jwt.decode(tok(), options={"verify_signature": False})
    assert check(tok()).email == "a@example.com"


def test_tid_mismatch_rejected_and_match_accepted():
    bad(tok(tid="99999999-2222-3333-4444-555555555555"))
    assert check(tok(tid=TENANT.upper())).sub == "sub-1"


@pytest.mark.parametrize("seg", ["common", "organizations", "consumers"])
def test_tenantless_issuer_is_config_error(seg: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SEEN_OIDC_CLIENT_ID", CID)
    monkeypatch.setenv("SEEN_OIDC_ISSUER", f"https://login.microsoftonline.com/{seg}/v2.0")
    with pytest.raises(OidcConfigError):
        OidcConfig.from_env()
    monkeypatch.setenv("SEEN_OIDC_ISSUER", f"https://idp.example.com/{seg}/v2.0")
    with pytest.raises(OidcConfigError):
        OidcConfig.from_env()


@pytest.mark.parametrize("iss", [
    "http://login.microsoftonline.com/" + TENANT + "/v2.0",
    "https://login.microsoftonline.com/not-a-guid/v2.0",
    "https://login.microsoftonline.com/" + TENANT,
])
def test_bad_entra_or_insecure_issuer_is_config_error(iss: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SEEN_OIDC_CLIENT_ID", CID)
    monkeypatch.setenv("SEEN_OIDC_ISSUER", iss)
    with pytest.raises(OidcConfigError):
        OidcConfig.from_env()


def test_localhost_http_issuer_allowed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SEEN_OIDC_CLIENT_ID", CID)
    monkeypatch.setenv("SEEN_OIDC_ISSUER", "http://localhost:9000/realm")
    assert OidcConfig.from_env() is not None


def test_kid_miss_refreshes_once_then_fails():
    f = jwks_of(jwk(OTHER, "other"))
    bad(tok(kid="k1"), jwks=f)
    assert f.calls == [False, True]


def test_kid_miss_recovers_after_rotation():
    state = {"n": 0}

    def f(refresh: bool) -> dict:
        state["n"] += 1
        return {"keys": [jwk(KEY)]} if refresh else {"keys": []}

    assert check(tok(), jwks=f).sub == "sub-1"


def test_jwks_unreachable_is_oidc_error():
    def f(refresh: bool) -> dict:
        raise OSError("boom https://secret")

    bad(tok(), jwks=f)


def test_malformed_tokens():
    bad("")
    bad("not.a.jwt")


def test_from_env(monkeypatch: pytest.MonkeyPatch):
    for k in ("SEEN_OIDC_ISSUER", "SEEN_OIDC_CLIENT_ID", "SEEN_OIDC_ALLOWED_DOMAINS"):
        monkeypatch.delenv(k, raising=False)
    assert OidcConfig.from_env() is None
    monkeypatch.setenv("SEEN_OIDC_ISSUER", ISS)
    with pytest.raises(OidcConfigError):  # half a config fails closed and loud, never "SSO silently off"
        OidcConfig.from_env()
    monkeypatch.setenv("SEEN_OIDC_CLIENT_ID", CID)
    monkeypatch.setenv("SEEN_OIDC_ALLOWED_DOMAINS", " example.com, example.org ,")
    cfg = OidcConfig.from_env()
    assert cfg == OidcConfig(ISS, CID, frozenset({"example.com", "example.org"}))


def test_no_allowed_domains_rejects_everyone():
    cfg = OidcConfig(ISS, CID, frozenset())
    with pytest.raises(OidcError):
        validate_id_token(tok(), "n1", cfg, jwks_of(jwk(KEY)))


# --- real fetcher, against a local http.server ---

class _H(BaseHTTPRequestHandler):
    hits: list[str] = []
    fail = False
    slow = 0.0

    def do_GET(self) -> None:  # noqa: N802
        _H.hits.append(self.path)
        port = self.server.server_address[1]
        if self.path.startswith("/nope"):
            self.send_error(404)
            return
        if self.path.endswith("/.well-known/openid-configuration"):
            body = {"jwks_uri": f"http://localhost:{port}/keys"}
        elif self.path == "/keys":
            time.sleep(_H.slow)
            if _H.fail:
                self.send_error(500)
                return
            body = {"keys": [jwk(KEY)]}
        else:
            self.send_error(404)
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a: Any) -> None:
        pass


@pytest.fixture
def server():
    _H.hits = []
    _H.fail = False
    _H.slow = 0.0
    s = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://localhost:{s.server_address[1]}"
    s.shutdown()


def test_fetcher_caches_and_refreshes(server: str):
    f = make_jwks_fetcher(server)
    assert f(False)["keys"][0]["kid"] == "k1"
    n = len(_H.hits)
    f(False)
    assert len(_H.hits) == n  # cached
    f(True)
    assert len(_H.hits) > n  # forced refresh


def _junk(i: int) -> str:
    return tok(kid=f"junk-{i}")


def test_junk_kids_cause_at_most_one_forced_fetch(server: str):
    now = [1000.0]
    f = make_jwks_fetcher(server, clock=lambda: now[0])
    for i in range(50):
        bad(_junk(i), jwks=f)
    keys_hits = lambda: _H.hits.count("/keys")  # noqa: E731
    assert keys_hits() == 2  # initial load + one forced refresh
    now[0] += 61
    bad(_junk(99), jwks=f)
    assert keys_hits() == 3  # window elapsed: one more forced refresh allowed
    bad(_junk(100), jwks=f)
    assert keys_hits() == 3
    assert check(tok(), jwks=f).sub == "sub-1"  # a known kid still validates from cache


def test_stale_keys_not_served_when_leader_fetch_fails(server: str):
    now = [0.0]
    f = make_jwks_fetcher(server, clock=lambda: now[0])
    f(False)
    now[0] = 3601  # past the 1 h TTL
    _H.fail, _H.slow = True, 0.3
    out: list[object] = []

    def call() -> None:
        try:
            out.append(f(False))
        except OidcError:
            out.append("err")

    ts = [threading.Thread(target=call) for _ in range(2)]
    ts[0].start()
    time.sleep(0.1)  # leader is mid-fetch; the second caller follows or leads, either must fail
    ts[1].start()
    [t.join() for t in ts]
    assert out == ["err", "err"]


def test_stale_keys_not_served_when_forced_refresh_throttled(server: str):
    now = [0.0]
    f = make_jwks_fetcher(server, clock=lambda: now[0])
    f(False)
    now[0] = 3590
    _H.fail = True
    with pytest.raises(OidcError):
        f(True)  # failed forced refresh still starts the throttle window
    now[0] = 3601
    with pytest.raises(OidcError):
        f(True)  # throttled and keys older than TTL: fail closed, no fetch
    bad(_junk(1), jwks=f)
    _H.fail = False
    assert f(False)["keys"]  # a normal call may refetch


def test_throttled_kid_miss_with_young_keys_fails_but_known_kid_validates(server: str):
    now = [0.0]
    f = make_jwks_fetcher(server, clock=lambda: now[0])
    bad(_junk(1), jwks=f)  # initial load + forced refresh
    now[0] = 10
    n = len(_H.hits)
    bad(_junk(2), jwks=f)
    assert check(tok(), jwks=f).sub == "sub-1"
    assert len(_H.hits) == n


def test_concurrent_cold_callers_share_one_fetch(server: str):
    f = make_jwks_fetcher(server)
    ts = [threading.Thread(target=f, args=(False,)) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert _H.hits.count("/keys") == 1


def test_fetcher_failures_are_oidc_error(server: str):
    with pytest.raises(OidcError):
        make_jwks_fetcher("http://example.com/x")(False)  # plain http, not localhost
    with pytest.raises(OidcError):
        make_jwks_fetcher(server + "/nope")(False)  # 404
    with pytest.raises(OidcError):
        make_jwks_fetcher("http://localhost:1")(False)  # refused


def test_entra_issuer_requires_tid():
    bad(tok(tid=json_null))  # present but null
    bad(tok(tid=None))  # absent: None drops the claim
    bad(tok(tid="99999999-2222-3333-4444-555555555555"))
    assert check(tok(tid=TENANT)).sub == "sub-1"


@pytest.mark.parametrize("email", ["Kim@example.com", "kim@Kexample.com", "kim@example.comK", "kım@example.com"])
def test_non_ascii_email_rejected_before_casefolding(email: str):
    """Real validator path: U+212A lowercases to ASCII 'k', so the check must run before .lower()."""
    cfg = OidcConfig(ISS, CID, frozenset({"example.com", "kexample.com"}))
    with pytest.raises(OidcError):
        validate_id_token(tok(email=email), "n1", cfg, jwks_of(jwk(KEY)))


def test_identity_carries_token_expiry():
    assert check(tok()).exp > time.time()


def test_client_id_without_issuer_also_refuses(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SEEN_OIDC_ISSUER", raising=False)
    monkeypatch.setenv("SEEN_OIDC_CLIENT_ID", CID)
    with pytest.raises(OidcConfigError):
        OidcConfig.from_env()
