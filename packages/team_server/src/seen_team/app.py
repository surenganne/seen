"""Seen team server (Phase 5 skeleton): receives sync batches, serves project aggregates, anchors audit heads.

Auth: project-scoped API keys (stored as SHA-256), bootstrap admin key from SEEN_TEAM_BOOTSTRAP_KEY.
Roles: member sees own detail and project aggregates; lead sees project aggregates; admin sees all aggregates.
"""


import hashlib
import hmac
import json
import os
import secrets
import time
from collections import Counter, defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, TeamApiKey, TeamAuditHead, TeamBatch, TeamChange, TeamInstall, TeamProject, TeamUser
from .oidc import Identity, OidcConfig, _get_json, make_jwks_fetcher, validate_id_token

DEFAULT_PORT = 47824
SECURITY_HEADERS = {"X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Permissions-Policy": "camera=(), microphone=()"}
MAX_FAILS, WINDOW_S = 8, 60
MAX_REQUESTS = 600  # per client per window, successes included
MAX_BODY = 2 * 1024 * 1024


def _add_missing_key_columns(engine: sa.Engine) -> None:
    """create_all never alters a table: databases made before key expiry/revocation get the two columns here."""
    have = {c["name"] for c in sa.inspect(engine).get_columns("team_api_keys")}
    with engine.begin() as c:
        for col in ("expires_at", "revoked_at"):
            if col not in have:
                c.execute(sa.text(f"ALTER TABLE team_api_keys ADD COLUMN {col} VARCHAR(40)"))
        if "origin" not in have:
            c.execute(sa.text("ALTER TABLE team_api_keys ADD COLUMN origin VARCHAR(16) NOT NULL DEFAULT 'manual'"))


def client_ip(request: Request) -> str:
    """The address to throttle. Behind N trusted proxies (SEEN_TEAM_PROXY_HOPS) take the entry the Nth proxy appended;
    otherwise the socket peer. X-Forwarded-For is never trusted unless told how many hops to trust."""
    hops = int(os.environ.get("SEEN_TEAM_PROXY_HOPS") or 0)
    if hops > 0:
        parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "?"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # content fields (prompt_text, summary, ...) are refused outright


class SkillIn(Strict):
    skill: str | None = Field(max_length=200)
    kind: str | None = Field(default=None, max_length=20)
    hash: str | None = Field(default=None, max_length=64)
    trigger: str | None = Field(default=None, max_length=20)
    status: str | None = Field(default=None, max_length=20)


class PolicyIn(Strict):
    policy: str = Field(max_length=200)
    met: bool


class FileIn(Strict):
    path: str = Field(max_length=500)
    added: int = Field(ge=0)
    removed: int = Field(ge=0)


class PiiIn(Strict):
    state: str | None = Field(default=None, max_length=20)
    counts: dict[str, Annotated[int, Field(ge=0)]] = Field(default={}, max_length=50)


class ChangeIn(Strict):
    id: str = Field(max_length=64)
    project_id: str = Field(max_length=64)
    session_id: str | None = Field(default=None, max_length=80)
    seq: int | None = Field(default=None, ge=0)
    started_at: str | None = Field(default=None, max_length=40)
    duration_s: int | None = Field(default=None, ge=0)
    tool: str = Field(default="claude-code", max_length=40)
    user_id: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    git_status: str | None = Field(default=None, max_length=20)
    file_count: int = Field(default=0, ge=0)
    lines_added: int = Field(default=0, ge=0)
    lines_removed: int = Field(default=0, ge=0)
    files: list[FileIn] | None = Field(default=None, max_length=500)
    tok_in: int | None = Field(default=None, ge=0)
    tok_out: int | None = Field(default=None, ge=0)
    tok_cache_read: int | None = Field(default=None, ge=0)
    tok_cache_write: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    price_version: str | None = Field(default=None, max_length=40)
    skills: list[SkillIn] | None = Field(default=None, max_length=100)
    policies: list[PolicyIn] | None = Field(default=None, max_length=200)
    pii: PiiIn | None = None


class HeadIn(Strict):
    at: str = Field(max_length=40)
    seq: int = Field(ge=0)
    hash: str = Field(min_length=64, max_length=64)


class AuditIn(Strict):
    """An audit event as the client sends it (allowlisted detail only). Validated so garbage is refused; the server
    stores only the anchored heads."""
    seq: int = Field(ge=0)
    event_id: str = Field(max_length=200)
    occurred_at: str = Field(max_length=40)
    actor_kind: str = Field(max_length=20)
    actor_id: str | None = Field(default=None, max_length=200)
    project_id: str | None = Field(default=None, max_length=64)
    session_id: str | None = Field(default=None, max_length=80)
    change_id: str | None = Field(default=None, max_length=64)
    type: str = Field(max_length=80)
    outcome: str | None = Field(default=None, max_length=20)
    prev_hash: str | None = Field(default=None, max_length=64)
    hash: str = Field(max_length=64)
    detail: dict[str, str | int | float | bool | None] = Field(default={}, max_length=30)


class BatchIn(Strict):
    install_id: str = Field(max_length=80)
    changes: list[ChangeIn] = Field(max_length=1000)
    audit_heads: list[HeadIn] = Field(default=[], max_length=100)
    audit: list[AuditIn] = Field(default=[], max_length=1000)


class KeyIn(Strict):
    project_id: str | None = Field(default=None, max_length=64)
    role: Literal["member", "lead", "admin"]
    user_id: str | None = Field(default=None, max_length=80)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ExchangeIn(Strict):
    id_token: str = Field(max_length=16384)
    nonce: str = Field(max_length=256)


class UserPatch(Strict):
    role: Literal["member", "lead", "admin"] | None = None
    active: bool | None = None


SSO_KEY_DAYS = 30


def create_app(url: str | None = None, reset: bool = False, oidc_validate: Callable[[str, str], Identity] | None = None) -> FastAPI:
    url = url or os.environ.get("SEEN_TEAM_DATABASE_URL") or "sqlite:///seen-team.db"
    cfg = OidcConfig.from_env()  # raises OidcConfigError on a partial or unsafe config: startup stops
    if oidc_validate is None and cfg is not None:
        fetcher = make_jwks_fetcher(cfg.issuer)  # one fetcher (and cache) for the process
        oidc_cfg = cfg

        def oidc_validate(token: str, nonce: str) -> Identity:  # noqa: F811
            return validate_id_token(token, nonce, oidc_cfg, fetcher)
    bootstrap_off = os.environ.get("SEEN_TEAM_BOOTSTRAP_DISABLE", "").strip().lower() in ("1", "true", "yes")
    boot = "" if bootstrap_off else os.environ.get("SEEN_TEAM_BOOTSTRAP_KEY", "")
    if os.environ.get("APP_ENV") == "production":
        if bootstrap_off and oidc_validate is None:
            raise SystemExit("Production with SEEN_TEAM_BOOTSTRAP_DISABLE=1 needs SEEN_OIDC_ISSUER and SEEN_OIDC_CLIENT_ID: no way to sign in.")
        if not bootstrap_off and len(boot) < 32:
            raise SystemExit("SEEN_TEAM_BOOTSTRAP_KEY must be set to 32+ random characters in production.")
    disco: dict[str, Any] = {"at": 0.0, "doc": None}
    engine = sa.create_engine(url, pool_pre_ping=True)
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    _add_missing_key_columns(engine)  # ponytail: skeleton uses create_all; move to Alembic before the first schema change
    Sess = sessionmaker(engine, expire_on_commit=False)
    fails: dict[str, deque[float]] = defaultdict(deque)
    hits: dict[str, deque[float]] = defaultdict(deque)  # every attempt, successes included
    prod = os.environ.get("APP_ENV") == "production"  # no unauthenticated API map in production
    app = FastAPI(title="Seen team server", version="0.1.0", docs_url=None if prod else "/docs",
                  redoc_url=None if prod else "/redoc", openapi_url=None if prod else "/openapi.json")

    @app.middleware("http")
    async def headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method in ("POST", "PUT", "PATCH"):
            cl = request.headers.get("content-length")
            if cl is None or not cl.isdigit():
                return JSONResponse({"detail": "Content-Length required"}, status_code=411, headers=SECURITY_HEADERS)
            if int(cl) > MAX_BODY:
                return JSONResponse({"detail": "request body too large"}, status_code=413, headers=SECURITY_HEADERS)
        resp = await call_next(request)
        resp.headers.update(SECURITY_HEADERS)
        return resp

    def db() -> Any:
        s = Sess()
        try:
            yield s
        finally:
            s.close()

    Db = Annotated[Session, Depends(db)]

    def throttle(request: Request) -> deque[float]:
        """Per-IP limiter shared by auth and the pre-auth exchange. Returns the failure queue: append to it on a failed attempt."""
        ip = client_ip(request)
        q, h = fails[ip], hits[ip]
        for dq in (q, h):
            while dq and dq[0] < time.monotonic() - WINDOW_S:
                dq.popleft()
        if len(q) >= MAX_FAILS or len(h) >= MAX_REQUESTS:  # locked: even a correct key waits, so the lockout is not an oracle
            raise HTTPException(429, "too many requests; retry later")
        h.append(time.monotonic())
        return q

    def auth(request: Request, s: Db, authorization: str = Header(default="")) -> TeamApiKey:
        q = throttle(request)
        token = authorization.removeprefix("Bearer ").strip()
        tb = token.encode("utf-8", "surrogatepass")
        if boot and hmac.compare_digest(tb, boot.encode()):
            return TeamApiKey(id="bootstrap", key_hash="", project_id=None, role="admin", created_at="")
        k = s.scalars(sa.select(TeamApiKey).where(TeamApiKey.key_hash == hashlib.sha256(tb).hexdigest())).first() if token else None
        if k is not None and (k.revoked_at or (k.expires_at and k.expires_at <= now())):
            k = None  # a revoked or expired key is indistinguishable from a wrong one
        if k is not None and k.origin == "sso":
            u = s.get(TeamUser, k.user_id)
            if u is None or not u.active:
                k = None  # deactivated or erased: the key dies with the user
            else:
                s.expunge(k)  # the role is read live from the user row; never write it back to the key
                k.role = u.role
        if k is None:
            q.append(time.monotonic())
            raise HTTPException(401, "invalid API key")
        return k

    Key = Annotated[TeamApiKey, Depends(auth)]

    def owns(s: Session, k: TeamApiKey, key_id: str) -> bool:
        """The same key, or (SSO) an earlier key of the same person: a re-login mints a new key but keeps the install."""
        if key_id == k.id:
            return True
        o = s.get(TeamApiKey, key_id) if k.origin == "sso" else None
        return o is not None and o.origin == "sso" and o.user_id == k.user_id

    def sees(k: TeamApiKey, pid: str) -> bool:
        return k.role == "admin" or k.project_id == pid or (k.origin == "sso" and k.role == "lead")

    def can_see(k: TeamApiKey, pid: str) -> None:
        if not sees(k, pid):
            raise HTTPException(403, "key is not scoped to this project")

    def need_oidc() -> Callable[[str, str], Identity]:
        if oidc_validate is None:
            raise HTTPException(503, "SSO is not configured")
        return oidc_validate

    @app.post("/auth/exchange")
    def exchange(body: ExchangeIn, request: Request, s: Db) -> dict[str, str]:
        """Trade an IdP id_token for a 30-day team key. Every failure is the same 401; nothing from the token is echoed or logged."""
        q = throttle(request)
        validate = need_oidc()
        try:
            ident = validate(body.id_token, body.nonce)
            if not ident.email.isascii():  # casefolding tricks (U+212A -> "k") must never reach the admin comparison
                raise ValueError
            email, t = ident.email.lower(), now()
            u = s.get(TeamUser, ident.sub)
            if u is None:
                admins = {a.strip().lower() for a in os.environ.get("SEEN_TEAM_ADMINS", "").split(",") if a.strip()}
                u = TeamUser(sub=ident.sub, email=email, role="admin" if email in admins else "member", active=True, first_seen=t, last_login=t)
                s.add(u)
                try:
                    s.flush()
                except IntegrityError:  # a simultaneous first login won the insert: continue with its row
                    s.rollback()
                    u = s.get(TeamUser, ident.sub)
                    if u is None:
                        raise
            if not u.active:
                raise ValueError
            u.email, u.last_login = email, t
            token = "seen_" + secrets.token_urlsafe(32)
            exp = (datetime.now(UTC) + timedelta(days=SSO_KEY_DAYS)).isoformat(timespec="seconds").replace("+00:00", "Z")
            s.add(TeamApiKey(id=secrets.token_hex(8), key_hash=hashlib.sha256(token.encode()).hexdigest(), project_id=None, role=u.role,
                             user_id=u.sub, created_at=t, expires_at=exp, origin="sso"))
            s.commit()
            return {"key": token, "expires_at": exp, "email": u.email, "role": u.role}
        except Exception:  # noqa: BLE001 - validation failures and surprises alike: one fixed 401, never a 500
            s.rollback()
            q.append(time.monotonic())
            raise HTTPException(401, "sign-in failed") from None

    @app.get("/auth/config")
    def auth_config(request: Request) -> dict[str, str]:
        throttle(request)
        if cfg is None:
            raise HTTPException(503, "SSO is not configured")
        try:
            if disco["doc"] is None or time.monotonic() - disco["at"] > 3600:
                raw = _get_json(cfg.issuer.rstrip("/") + "/.well-known/openid-configuration")
                doc = {f: raw.get(f) for f in ("authorization_endpoint", "token_endpoint")}
                if not all(isinstance(v, str) and v.startswith("https://") for v in doc.values()):
                    raise ValueError  # never cache or serve a document we would not trust
                disco["doc"], disco["at"] = doc, time.monotonic()
            d = disco["doc"]
            return {"authorization_endpoint": d["authorization_endpoint"], "token_endpoint": d["token_endpoint"], "client_id": cfg.client_id}
        except Exception:  # noqa: BLE001
            raise HTTPException(503, "SSO provider unavailable") from None

    @app.get("/auth/me")
    def me(k: Key, s: Db) -> dict[str, str | None]:
        u = s.get(TeamUser, k.user_id) if k.origin == "sso" else None
        return {"email": u.email if u else None, "role": k.role}

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, e: RequestValidationError) -> JSONResponse:
        # loc and type only: pydantic's `input`/`ctx` would echo request bodies (id_tokens included)
        return JSONResponse({"detail": [{"loc": list(x["loc"]), "type": x["type"]} for x in e.errors()]}, status_code=422, headers=SECURITY_HEADERS)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, e: HTTPException) -> JSONResponse:
        return JSONResponse({"detail": e.detail}, status_code=e.status_code, headers=SECURITY_HEADERS)

    @app.post("/api/keys")
    def create_key(body: KeyIn, k: Key, s: Db) -> dict[str, str]:
        if k.role != "admin":
            raise HTTPException(403, "admin only")
        if body.role == "member" and not body.user_id:
            raise HTTPException(422, "member keys must be bound to a user_id")
        token = "seen_" + secrets.token_urlsafe(32)
        exp = (datetime.now(UTC) + timedelta(days=body.expires_in_days)).isoformat(timespec="seconds").replace("+00:00", "Z") \
            if body.expires_in_days else None
        row = TeamApiKey(id=secrets.token_hex(8), key_hash=hashlib.sha256(token.encode()).hexdigest(), project_id=body.project_id,
                         role=body.role, user_id=body.user_id, created_at=now(), expires_at=exp)
        s.add(row)
        s.commit()
        return {"id": row.id, "key": token}  # shown once; only the hash is stored

    def admin_only(k: TeamApiKey) -> None:
        if k.role != "admin":
            raise HTTPException(403, "admin only")

    @app.get("/api/keys")
    def list_keys(k: Key, s: Db) -> list[dict[str, Any]]:
        admin_only(k)
        live = {u.sub: u.role for u in s.scalars(sa.select(TeamUser))}  # an SSO key's role is the user's current one
        return [{"id": r.id, "role": live.get(r.user_id or "", r.role) if r.origin == "sso" else r.role, "origin": r.origin,
                 "project_id": r.project_id, "user_id": r.user_id, "created_at": r.created_at,
                 "expires_at": r.expires_at, "revoked_at": r.revoked_at}
                for r in s.scalars(sa.select(TeamApiKey).order_by(TeamApiKey.created_at))]

    @app.delete("/api/keys/{key_id}")
    def revoke_key(key_id: str, k: Key, s: Db) -> dict[str, str]:
        admin_only(k)
        row = s.get(TeamApiKey, key_id)
        if row is None:
            raise HTTPException(404, "no such key")
        row.revoked_at = row.revoked_at or now()
        s.commit()
        return {"id": row.id, "revoked_at": row.revoked_at}

    @app.get("/api/users")
    def list_users(k: Key, s: Db) -> list[dict[str, Any]]:
        admin_only(k)
        return [{"sub": u.sub, "email": u.email, "role": u.role, "active": u.active, "last_login": u.last_login}
                for u in s.scalars(sa.select(TeamUser).order_by(TeamUser.email))]

    @app.put("/api/users/{sub}")
    def update_user(sub: str, body: UserPatch, k: Key, s: Db) -> dict[str, Any]:
        admin_only(k)
        u = s.get(TeamUser, sub)
        if u is None:
            raise HTTPException(404, "no such user")
        role, active = body.role or u.role, u.active if body.active is None else body.active
        if u.role == "admin" and u.active and not (role == "admin" and active) and not s.scalars(
                sa.select(TeamUser).where(TeamUser.role == "admin", TeamUser.active.is_(True), TeamUser.sub != sub)).first():
            raise HTTPException(409, "cannot remove the last active admin")
        u.role, u.active = role, active
        s.commit()
        return {"sub": u.sub, "email": u.email, "role": u.role, "active": u.active, "last_login": u.last_login}

    @app.delete("/api/users/{user_id}")
    def erase_user(user_id: str, k: Key, s: Db) -> dict[str, int]:
        """DPDP erasure: the person's changes go, their keys stop working. Audit-head anchors hold only hashes and stay."""
        admin_only(k)
        n = s.execute(sa.delete(TeamChange).where(TeamChange.user_id == user_id)).rowcount  # type: ignore[attr-defined]
        keys = list(s.scalars(sa.select(TeamApiKey).where(TeamApiKey.user_id == user_id, TeamApiKey.revoked_at.is_(None))))
        for row in keys:
            row.revoked_at = now()
        u = s.get(TeamUser, user_id)
        if u is not None:  # tombstone: the email is personal data and goes, the sub stays so re-entry needs an explicit re-activation
            u.email, u.active = "", False
        s.commit()
        return {"changes": n, "keys_revoked": len(keys)}

    @app.delete("/api/projects/{pid}")
    def erase_project(pid: str, k: Key, s: Db) -> dict[str, int]:
        admin_only(k)
        n = s.execute(sa.delete(TeamChange).where(TeamChange.project_id == pid)).rowcount  # type: ignore[attr-defined]
        s.execute(sa.delete(TeamProject).where(TeamProject.id == pid))
        s.commit()
        return {"changes": n}

    @app.post("/api/sync")
    def sync(body: BatchIn, k: Key, s: Db, x_idempotency_key: str = Header(..., max_length=128)) -> dict[str, Any]:
        sso = k.origin == "sso"  # an SSO key writes its own changes at any role and for any project
        if not sso and (k.role != "member" or not k.user_id):
            raise HTTPException(403, "only member keys (bound to a user) can send changes")
        def same_writer(key_id: str) -> bool:
            return owns(s, k, key_id)

        prior = s.scalars(sa.select(TeamBatch).where(TeamBatch.key_id == k.id, TeamBatch.idempotency_key == x_idempotency_key)).first()
        if prior:
            return {**json.loads(prior.response), "duplicate": True}
        t = now()
        inst = s.get(TeamInstall, body.install_id)
        if inst is None:
            s.add(TeamInstall(install_id=body.install_id, key_id=k.id, first_seen=t))
        elif not same_writer(inst.key_id):
            raise HTTPException(403, "this install id belongs to another key")
        if sso:
            body.changes = [c.model_copy(update={"user_id": k.user_id}) for c in body.changes]  # never trust the client's value
        for c in body.changes:
            if not sso:
                can_see(k, c.project_id)
                if c.user_id != k.user_id:
                    raise HTTPException(403, "member keys can only send their own changes")
            old = s.get(TeamChange, c.id)
            if old is not None and (old.project_id != c.project_id or not same_writer(old.writer_key)):
                raise HTTPException(409, f"change {c.id} already belongs to another project or writer")
        for h in body.audit_heads:
            old_h = s.get(TeamAuditHead, (body.install_id, h.seq))
            if old_h is not None and old_h.hash != h.hash:
                raise HTTPException(409, f"head seq {h.seq} was anchored with a different hash: the local chain was rewritten")
        for c in body.changes:
            if s.get(TeamProject, c.project_id) is None:
                s.add(TeamProject(id=c.project_id, first_seen=t))
            s.merge(TeamChange(id=c.id, project_id=c.project_id, user_id=c.user_id, started_at=c.started_at,
                               payload=c.model_dump(exclude_none=True), writer_key=k.id, received_at=t))
        for h in body.audit_heads:
            if s.get(TeamAuditHead, (body.install_id, h.seq)) is None:  # append-only
                s.add(TeamAuditHead(install_id=body.install_id, seq=h.seq, hash=h.hash, at=h.at, received_at=t))
        last = max(body.audit_heads, key=lambda h: h.seq) if body.audit_heads else None
        resp = {"accepted": len(body.changes), "duplicate": False,
                "anchored": {"seq": last.seq, "hash": last.hash} if last else None}
        s.add(TeamBatch(key_id=k.id, idempotency_key=x_idempotency_key, accepted=len(body.changes), response=json.dumps(resp), received_at=t))
        s.commit()
        return resp

    @app.get("/api/anchors/{install_id}")
    def anchor(install_id: str, k: Key, s: Db) -> dict[str, Any]:
        inst = s.get(TeamInstall, install_id)
        if k.role != "admin" and (inst is None or not owns(s, k, inst.key_id)):
            raise HTTPException(403, "only the owning key or an admin can read this install's anchors")
        h = s.scalars(sa.select(TeamAuditHead).where(TeamAuditHead.install_id == install_id).order_by(TeamAuditHead.seq.desc())).first()
        if h is None:
            raise HTTPException(404, "no anchored heads")
        return {"seq": h.seq, "hash": h.hash, "at": h.at, "received_at": h.received_at}

    def rows(s: Session, pid: str, days: int | None = None) -> list[TeamChange]:
        q = sa.select(TeamChange).where(TeamChange.project_id == pid)
        if days:
            q = q.where(TeamChange.started_at >= (datetime.now(UTC) - timedelta(days=days)).isoformat().replace("+00:00", "Z"))
        return list(s.scalars(q.order_by(TeamChange.started_at.desc())))

    @app.get("/api/projects")
    def projects(k: Key, s: Db) -> list[dict[str, Any]]:
        out = []
        for p in s.scalars(sa.select(TeamProject).order_by(TeamProject.id)):
            if sees(k, p.id):
                rs = rows(s, p.id)
                out.append({"id": p.id, "name": p.id, "changes": len(rs), "last_change_at": rs[0].started_at if rs else None,
                            "cost_7d": round(sum(r.payload.get("cost_usd") or 0 for r in rows(s, p.id, 7)), 4)})
        return out

    @app.get("/api/projects/{pid}/overview")
    def overview(pid: str, k: Key, s: Db, range_: Annotated[int, Query(alias="range")] = 7) -> dict[str, Any]:
        can_see(k, pid)
        if range_ not in (7, 14, 28):
            raise HTTPException(422, "range must be 7, 14 or 28")
        rs = [r.payload for r in rows(s, pid, range_)]
        by_day: dict[str, float] = Counter()
        for r in rs:
            by_day[(r.get("started_at") or "")[:10]] += r.get("cost_usd") or 0
        skills = Counter(sk["skill"] for r in rs for sk in r.get("skills") or [] if sk.get("skill"))
        models: dict[str, dict[str, Any]] = {}
        for r in rs:
            m = models.setdefault(r.get("model") or "unknown", {"model": r.get("model") or "unknown", "changes": 0, "tok_out": 0, "cost_usd": 0.0})
            m["changes"] += 1
            m["tok_out"] += r.get("tok_out") or 0
            m["cost_usd"] += r.get("cost_usd") or 0
        pii_types: Counter[str] = Counter()
        for r in rs:
            pii_types.update((r.get("pii") or {}).get("counts") or {})
        return {"range": range_, "tiles": {"changes": len(rs), "lines_added": sum(r.get("lines_added", 0) for r in rs),
                                           "lines_removed": sum(r.get("lines_removed", 0) for r in rs),
                                           "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rs), 4),
                                           "policy_missed": sum(any(not p["met"] for p in r.get("policies") or []) for r in rs),
                                           "pii_changes": sum(1 for r in rs if (r.get("pii") or {}).get("counts"))},
                "cost_by_day": [{"date": d, "by_tool": {"claude-code": round(v, 6)}} for d, v in sorted(by_day.items())],
                "top_skills": [{"skill_id": n, "runs": c} for n, c in skills.most_common(10)],
                "by_model": sorted(models.values(), key=lambda m: -m["cost_usd"]),
                "pii_by_type": [{"type": t, "count": c} for t, c in pii_types.most_common()]}

    @app.get("/api/projects/{pid}/changes")
    def changes(pid: str, k: Key, s: Db, user_id: str | None = None) -> list[dict[str, Any]]:
        """Per-person detail is private by default: a member sees their own (from the key), nobody else's."""
        can_see(k, pid)
        if k.role != "member" or not k.user_id or (user_id is not None and user_id != k.user_id):
            raise HTTPException(403, "per-person detail is only visible to that person")
        return [r.payload for r in rows(s, pid) if r.user_id == k.user_id]

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(), host=os.environ.get("SEEN_TEAM_HOST", "127.0.0.1"),
                port=int(os.environ.get("SEEN_TEAM_PORT", DEFAULT_PORT)), server_header=False)


if __name__ == "__main__":
    main()
