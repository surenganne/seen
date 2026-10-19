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
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, TeamApiKey, TeamAuditHead, TeamBatch, TeamChange, TeamInstall, TeamProject

DEFAULT_PORT = 47824
SECURITY_HEADERS = {"X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Permissions-Policy": "camera=(), microphone=()"}
MAX_FAILS, WINDOW_S = 8, 60


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
    added: int
    removed: int


class PiiIn(Strict):
    state: str | None = Field(default=None, max_length=20)
    counts: dict[str, int] = {}


class ChangeIn(Strict):
    id: str = Field(max_length=64)
    project_id: str = Field(max_length=64)
    session_id: str | None = Field(default=None, max_length=80)
    seq: int | None = None
    started_at: str | None = Field(default=None, max_length=40)
    duration_s: int | None = None
    tool: str = Field(default="claude-code", max_length=40)
    user_id: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    git_status: str | None = Field(default=None, max_length=20)
    mem_state: str | None = Field(default=None, max_length=20)
    file_count: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    files: list[FileIn] | None = None
    tok_in: int | None = None
    tok_out: int | None = None
    tok_cache_read: int | None = None
    tok_cache_write: int | None = None
    cost_usd: float | None = None
    price_version: str | None = Field(default=None, max_length=40)
    skills: list[SkillIn] | None = None
    policies: list[PolicyIn] | None = None
    pii: PiiIn | None = None


class HeadIn(Strict):
    at: str = Field(max_length=40)
    seq: int
    hash: str = Field(min_length=64, max_length=64)


class BatchIn(Strict):
    install_id: str = Field(max_length=80)
    changes: list[ChangeIn] = Field(max_length=1000)
    audit_heads: list[HeadIn] = []
    audit: list[dict[str, Any]] = []


class KeyIn(Strict):
    project_id: str | None = Field(default=None, max_length=64)
    role: Literal["member", "lead", "admin"]
    user_id: str | None = Field(default=None, max_length=80)


def create_app(url: str | None = None, reset: bool = False) -> FastAPI:
    url = url or os.environ.get("SEEN_TEAM_DATABASE_URL") or "sqlite:///seen-team.db"
    boot = os.environ.get("SEEN_TEAM_BOOTSTRAP_KEY", "")
    if os.environ.get("APP_ENV") == "production" and len(boot) < 32:
        raise SystemExit("SEEN_TEAM_BOOTSTRAP_KEY must be set to 32+ random characters in production.")
    engine = sa.create_engine(url, pool_pre_ping=True)
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)  # ponytail: skeleton uses create_all; move to Alembic before the first schema change
    Sess = sessionmaker(engine, expire_on_commit=False)
    fails: dict[str, deque[float]] = defaultdict(deque)
    app = FastAPI(title="Seen team server", version="0.1.0")

    @app.middleware("http")
    async def headers(request: Request, call_next):  # type: ignore[no-untyped-def]
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

    def auth(request: Request, s: Db, authorization: str = Header(default="")) -> TeamApiKey:
        ip = request.client.host if request.client else "?"
        q = fails[ip]
        while q and q[0] < time.monotonic() - WINDOW_S:
            q.popleft()
        if len(q) >= MAX_FAILS:  # locked: even a correct key waits, so the lockout is not an oracle
            raise HTTPException(429, "too many failed attempts; retry later")
        token = authorization.removeprefix("Bearer ").strip()
        tb = token.encode("utf-8", "surrogatepass")
        if boot and hmac.compare_digest(tb, boot.encode()):
            return TeamApiKey(id="bootstrap", key_hash="", project_id=None, role="admin", created_at="")
        k = s.scalars(sa.select(TeamApiKey).where(TeamApiKey.key_hash == hashlib.sha256(tb).hexdigest())).first() if token else None
        if k is None:
            q.append(time.monotonic())
            raise HTTPException(401, "invalid API key")
        return k

    Key = Annotated[TeamApiKey, Depends(auth)]

    def can_see(k: TeamApiKey, pid: str) -> None:
        if k.role != "admin" and k.project_id != pid:
            raise HTTPException(403, "key is not scoped to this project")

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
        row = TeamApiKey(id=secrets.token_hex(8), key_hash=hashlib.sha256(token.encode()).hexdigest(), project_id=body.project_id,
                         role=body.role, user_id=body.user_id, created_at=now())
        s.add(row)
        s.commit()
        return {"id": row.id, "key": token}  # shown once; only the hash is stored

    @app.post("/api/sync")
    def sync(body: BatchIn, k: Key, s: Db, x_idempotency_key: str = Header(..., max_length=128)) -> dict[str, Any]:
        prior = s.scalars(sa.select(TeamBatch).where(TeamBatch.key_id == k.id, TeamBatch.idempotency_key == x_idempotency_key)).first()
        if prior:
            return {**json.loads(prior.response), "duplicate": True}
        t = now()
        inst = s.get(TeamInstall, body.install_id)
        if inst is None:
            s.add(TeamInstall(install_id=body.install_id, key_id=k.id, first_seen=t))
        elif inst.key_id != k.id:
            raise HTTPException(403, "this install id belongs to another key")
        for c in body.changes:
            can_see(k, c.project_id)
            if k.role == "member" and c.user_id != k.user_id:
                raise HTTPException(403, "member keys can only send their own changes")
            old = s.get(TeamChange, c.id)
            if old is not None and (old.project_id != c.project_id or old.writer_key != k.id):
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
        if k.role != "admin" and (inst is None or inst.key_id != k.id):
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
            if k.role == "admin" or k.project_id == p.id:
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
                                           "pii_changes": sum(1 for r in rs if (r.get("pii") or {}).get("counts")),
                                           "mem_loaded_pct": round(sum(r.get("mem_state") == "loaded" for r in rs) / len(rs), 4) if rs else None},
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
