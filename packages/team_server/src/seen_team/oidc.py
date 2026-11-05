"""OIDC id_token validation for the team server (Entra ID). Standalone: wired into the app later.

Never log or echo a token, code or verifier: every failure is OidcError("invalid token").
"""

from __future__ import annotations

import hmac
import json
import os
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
_TIMEOUT_S = 10
_MAX_BYTES = 1_000_000


class OidcError(Exception):
    """Fixed-message failure; never carries token or response content."""


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
        if claims.get("email_verified", True) is False:
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


def make_jwks_fetcher(issuer: str) -> Callable[[bool], dict[str, Any]]:
    """Real JWKS source: discovery document -> jwks_uri, cached for an hour; refresh=True bypasses the cache."""
    lock = threading.Lock()
    cache: list[Any] = [0.0, {}]

    def fetch(refresh: bool) -> dict[str, Any]:
        with lock:
            if not refresh and cache[1] and time.monotonic() - cache[0] < _JWKS_TTL_S:
                return dict(cache[1])
            try:
                disc = _get_json(issuer.rstrip("/") + "/.well-known/openid-configuration")
                keys = _get_json(str(disc.get("jwks_uri", "")))
            except Exception:  # noqa: BLE001
                raise OidcError(_FAIL) from None
            cache[0], cache[1] = time.monotonic(), keys
            return dict(keys)

    return fetch
