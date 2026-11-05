"""OIDC id_token validation for the team server (Entra ID). Standalone: wired into the app later.

Never log or echo a token, code or verifier: every failure is OidcError("invalid token").
"""

from __future__ import annotations

import hmac
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jwt

_FAIL = "invalid token"
_ALGS = ["RS256"]
_LEEWAY_S = 60
_JWKS_TTL_S = 3600
_FORCED_MIN_S = 60
_TIMEOUT_S = 10
_MAX_BYTES = 1_000_000


class OidcError(Exception):
    """Fixed-message failure; never carries token or response content."""


class OidcConfigError(ValueError):
    """Unsafe SSO configuration; the app must refuse to start rather than run unpinned."""


_ENTRA_HOST = "login.microsoftonline.com"
_TENANTLESS = {"common", "organizations", "consumers"}
_GUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_V2_PATH = re.compile(r"^/([^/]+)/v2\.0$")


def _check_issuer(issuer: str) -> None:
    u = urllib.parse.urlsplit(issuer)
    local = u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1")
    if (u.scheme != "https" and not local) or not u.hostname:
        raise OidcConfigError("SEEN_OIDC_ISSUER must be https")
    if _TENANTLESS & {seg.lower() for seg in u.path.split("/")}:
        raise OidcConfigError("SEEN_OIDC_ISSUER must be tenant-specific")
    if u.hostname == _ENTRA_HOST:
        m = _V2_PATH.match(u.path)
        if not m or not _GUID.match(m.group(1)):
            raise OidcConfigError("SEEN_OIDC_ISSUER must be https://login.microsoftonline.com/<tenant-guid>/v2.0")


def _issuer_tenant(issuer: str) -> str | None:
    u = urllib.parse.urlsplit(issuer)
    m = _V2_PATH.match(u.path)
    return m.group(1).lower() if m and u.hostname == _ENTRA_HOST else None


@dataclass(frozen=True)
class OidcConfig:
    issuer: str
    client_id: str
    allowed_domains: frozenset[str]

    @classmethod
    def from_env(cls) -> OidcConfig | None:
        issuer = os.environ.get("SEEN_OIDC_ISSUER", "").strip()
        client_id = os.environ.get("SEEN_OIDC_CLIENT_ID", "").strip()
        if not issuer or not client_id:
            return None
        _check_issuer(issuer)
        raw = os.environ.get("SEEN_OIDC_ALLOWED_DOMAINS", "")
        domains = frozenset(d.strip().lower() for d in raw.split(",") if d.strip())
        return cls(issuer, client_id, domains)


@dataclass(frozen=True)
class Identity:
    sub: str
    email: str


def _domain_ok(email: object, allowed: frozenset[str]) -> str | None:
    if not isinstance(email, str) or email.count("@") != 1:
        return None
    local, domain = email.lower().split("@")
    return f"{local}@{domain}" if local and domain in allowed else None


def _find_key(kid: str, jwks: Callable[[bool], dict[str, Any]]) -> dict[str, Any] | None:
    for refresh in (False, True):  # a kid miss refreshes exactly once
        for k in jwks(refresh).get("keys", []):
            if k.get("kid") == kid:
                return dict(k)
    return None


def validate_id_token(token: str, nonce: str, cfg: OidcConfig, jwks: Callable[[bool], dict[str, Any]]) -> Identity:
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if header.get("alg") not in _ALGS or not isinstance(kid, str):
            raise OidcError(_FAIL)
        jwk = _find_key(kid, jwks)
        if jwk is None or jwk.get("kty") != "RSA":
            raise OidcError(_FAIL)
        claims = jwt.decode(
            token,
            jwt.PyJWK(jwk),
            algorithms=_ALGS,
            audience=cfg.client_id,
            issuer=cfg.issuer,
            leeway=_LEEWAY_S,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
        got = claims.get("nonce")
        if not nonce or not isinstance(got, str) or not hmac.compare_digest(got.encode(), nonce.encode()):
            raise OidcError(_FAIL)
        # An absent email_verified is accepted only because the issuer is tenant-pinned (from_env + required tid check).
        if "email_verified" in claims and claims["email_verified"] is not True:
            raise OidcError(_FAIL)
        tenant = _issuer_tenant(cfg.issuer)
        if tenant is not None and ("tid" not in claims or str(claims["tid"]).lower() != tenant):
            raise OidcError(_FAIL)
        email = _domain_ok(claims.get("email"), cfg.allowed_domains)
        sub = claims["sub"]
        if email is None or not isinstance(sub, str) or not sub:
            raise OidcError(_FAIL)
        return Identity(sub, email)
    except OidcError:
        raise
    except Exception:  # noqa: BLE001 - any failure, including fetcher errors, maps to the fixed string
        raise OidcError(_FAIL) from None


def _https_or_localhost(url: str) -> None:
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" and not (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1")):
        raise OidcError(_FAIL)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a: Any, **k: Any) -> None:
        return None


def _get_json(url: str) -> dict[str, Any]:
    _https_or_localhost(url)
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(url, timeout=_TIMEOUT_S) as r:  # noqa: S310 - scheme checked above
        data = json.loads(r.read(_MAX_BYTES + 1)[:_MAX_BYTES])
    if not isinstance(data, dict):
        raise OidcError(_FAIL)
    return data


def make_jwks_fetcher(
    issuer: str, clock: Callable[[], float] = time.monotonic
) -> Callable[[bool], dict[str, Any]]:
    """Real JWKS source: discovery -> jwks_uri, cached 1 h. refresh=True is rate-limited to one fetch per 60 s.

    State is guarded by a short lock; the network fetch runs outside it and is single-flight.
    """
    lock = threading.Lock()
    st: dict[str, Any] = {"at": 0.0, "keys": None, "forced": None, "inflight": None}

    def fetch(refresh: bool) -> dict[str, Any]:
        with lock:
            now, keys = clock(), st["keys"]
            fresh = keys is not None and now - st["at"] <= _JWKS_TTL_S
            if fresh and not refresh:
                return dict(keys)
            if refresh and st["forced"] is not None and now - st["forced"] < _FORCED_MIN_S:
                if fresh:
                    return dict(keys)  # throttled: a junk kid cannot force a network call
                raise OidcError(_FAIL)  # throttled and past the TTL: fail closed, no grace period
            if refresh:
                st["forced"] = now
            ev: threading.Event | None = st["inflight"]
            leader = ev is None
            if leader:
                ev = st["inflight"] = threading.Event()
        assert ev is not None
        if not leader:
            ev.wait(_TIMEOUT_S * 2 + 1)
            with lock:
                if st["keys"] is None or clock() - st["at"] > _JWKS_TTL_S:
                    raise OidcError(_FAIL)  # leader failed and the cache is past the TTL
                return dict(st["keys"])
        try:
            disc = _get_json(issuer.rstrip("/") + "/.well-known/openid-configuration")
            fresh = _get_json(str(disc.get("jwks_uri", "")))
            with lock:
                st["keys"], st["at"] = fresh, clock()
            return dict(fresh)
        except Exception:  # noqa: BLE001
            raise OidcError(_FAIL) from None
        finally:
            with lock:
                st["inflight"] = None
            ev.set()

    return fetch
