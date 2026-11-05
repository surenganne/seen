import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from seen_team.oidc import Identity, OidcConfig, OidcError, make_jwks_fetcher, validate_id_token

ISS = "https://login.microsoftonline.com/tenant-1/v2.0"
CID = "client-1"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CFG = OidcConfig(ISS, CID, frozenset({"minfytech.com"}))


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


def tok(key: Any = KEY, kid: str = "k1", alg: str = "RS256", **over: Any) -> str:
    now = int(time.time())
    claims = {"iss": ISS, "aud": CID, "sub": "sub-1", "iat": now, "exp": now + 600,
              "nonce": "n1", "email": "a@minfytech.com", **over}
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


def check(token: str, jwks=None, nonce: str = "n1") -> Identity:
    return validate_id_token(token, nonce, CFG, jwks or jwks_of(jwk(KEY)))


def bad(token: str, **kw: Any) -> None:
    with pytest.raises(OidcError) as e:
        check(token, **kw)
    assert str(e.value) == "invalid token"


def test_valid_token():
    assert check(tok()) == Identity("sub-1", "a@minfytech.com")


def test_email_normalised_lowercase():
    assert check(tok(email="A@MinfyTech.com")).email == "a@minfytech.com"


def test_rejects_alg_none_and_hs256_confusion():
    bad(tok(key=None, alg="none"))
    now = int(time.time())
    hs = jwt.encode({"iss": ISS, "aud": CID, "sub": "s", "iat": now, "exp": now + 60, "nonce": "n1",
                     "email": "a@minfytech.com"}, "x" * 40, algorithm="HS256", headers={"kid": "k1"})
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
    "a@evil-minfytech.com", "a@minfytech.com.evil.io", "a@@minfytech.com", "a@x@minfytech.com",
    "minfytech.com", "a@", "a@sub.minfytech.com", "", 5,
])
def test_email_domain_exact_match_rejects(email):
    bad(tok(email=email))


def test_email_missing_rejected():
    bad(tok(email=None))


def test_unverified_email_rejected_when_claim_present():
    bad(tok(email_verified=False))
    assert check(tok(email_verified=True)).email == "a@minfytech.com"


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
    assert OidcConfig.from_env() is None
    monkeypatch.setenv("SEEN_OIDC_CLIENT_ID", CID)
    monkeypatch.setenv("SEEN_OIDC_ALLOWED_DOMAINS", " MinfyTech.com, example.org ,")
    cfg = OidcConfig.from_env()
    assert cfg == OidcConfig(ISS, CID, frozenset({"minfytech.com", "example.org"}))


def test_no_allowed_domains_rejects_everyone():
    cfg = OidcConfig(ISS, CID, frozenset())
    with pytest.raises(OidcError):
        validate_id_token(tok(), "n1", cfg, jwks_of(jwk(KEY)))


# --- real fetcher, against a local http.server ---

class _H(BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        _H.hits.append(self.path)
        port = self.server.server_address[1]
        if self.path.startswith("/nope"):
            self.send_error(404)
            return
        if self.path.endswith("/.well-known/openid-configuration"):
            body = {"jwks_uri": f"http://localhost:{port}/keys"}
        elif self.path == "/keys":
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


def test_fetcher_failures_are_oidc_error(server: str):
    with pytest.raises(OidcError):
        make_jwks_fetcher("http://example.com/x")(False)  # plain http, not localhost
    with pytest.raises(OidcError):
        make_jwks_fetcher(server + "/nope")(False)  # 404
    with pytest.raises(OidcError):
        make_jwks_fetcher("http://localhost:1")(False)  # refused
