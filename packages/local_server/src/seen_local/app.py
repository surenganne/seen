"""Seen local dashboard: the read API of section 12 over SQLite, plus the web build."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from seen_core import audit, brand, config, paths, pricing
from seen_core.db import ledger_session
from seen_core.db.models import Project, Session

from . import queries
from . import schemas as S

DEFAULT_PORT = 47821
ANCHOR_NOTE = ("Not anchored off this machine: the chain catches bugs, partial edits and clumsy tampering, "
               "but someone with write access to this machine can rebuild it. Anchoring arrives with team sync.")


def get_db() -> Iterator[DB]:
    db = ledger_session()
    try:
        yield db
    finally:
        db.close()


Db = Annotated[DB, Depends(get_db)]
Range = Annotated[int, Query(alias="range", description="7, 14 or 28 days")]


def _verify() -> S.VerifyOut:
    v = audit.verify()
    return S.VerifyOut(ok=v.ok, count=v.count, head=v.head, head_seq=v.head_seq, break_seq=v.break_seq, expected=v.expected,
                       found=v.found, reason=v.reason, verified_at=v.verified_at, anchored=False, anchor_note=ANCHOR_NOTE)


CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "font-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'")
SECURITY_HEADERS = {"X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                    "Content-Security-Policy": CSP, "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()"}


def allowed_hosts() -> list[str]:
    extra = [h.strip() for h in os.environ.get("SEEN_ALLOWED_HOSTS", "").split(",") if h.strip()]
    return ["127.0.0.1", "localhost", "[::1]", *extra]


def create_app(web_dist: Path | None = None) -> FastAPI:
    from fastapi import Request, Response
    from fastapi.responses import JSONResponse
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app = FastAPI(title=f"{brand.NAME} local API", version=brand.VERSION)
    state: dict[str, S.VerifyOut] = {}

    @app.middleware("http")
    async def guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        # unsafe methods need a custom header: a cross-site page can't send it without a CORS preflight we never grant
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.headers.get("x-seen-request") != "1":
            resp: Response = JSONResponse({"detail": "missing X-Seen-Request header"}, status_code=403)
        else:
            resp = await call_next(request)
        resp.headers.update(SECURITY_HEADERS)
        return resp

    # outermost: reject DNS-rebound Host headers before anything else runs
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())

    def verified() -> S.VerifyOut:
        if "v" not in state:
            state["v"] = _verify()  # runs when the dashboard starts (11A rule 5)
        return state["v"]

    def project_or_404(db: DB, pid: str) -> Project:
        p = db.get(Project, pid)
        if p is None:
            raise HTTPException(404, "project not found")
        return p

    @app.get("/api/projects", response_model=list[S.ProjectOut])
    def projects(db: Db) -> list[S.ProjectOut]:
        return [queries.project_out(db, p) for p in db.scalars(select(Project).order_by(Project.name))]

    @app.get("/api/projects/{pid}/overview", response_model=S.Overview)
    def overview(pid: str, db: Db, range_: Range = 7) -> S.Overview:
        if range_ not in (7, 14, 28):
            raise HTTPException(422, "range must be 7, 14 or 28")
        project_or_404(db, pid)
        return queries.overview(db, pid, range_, verified().ok)

    @app.get("/api/projects/{pid}/changes", response_model=S.ChangePage)
    def changes(pid: str, db: Db, tool: str | None = None, status: str | None = None, q: str | None = None,
                file: str | None = None, skill: str | None = None, policy_missed: bool | None = None,
                mem: Literal["loaded", "missed", "none"] | None = None, pii: bool | None = None,
                days: int | None = Query(None, ge=1, le=3650), sort: str = "time",
                dir: Literal["asc", "desc"] = "desc") -> S.ChangePage:
        project_or_404(db, pid)
        return queries.changes(db, pid, tool=tool, status=status, q=q, file=file, skill=skill, policy_missed=policy_missed,
                               mem=mem, pii=pii, days=days, sort=sort, dir=dir)

    @app.get("/api/changes/{cid}", response_model=S.ChangeDetail)
    def change(cid: str, db: Db) -> S.ChangeDetail:
        d = queries.change_detail(db, cid, config.load()["pii"]["store_prompt_text"])
        if d is None:
            raise HTTPException(404, "change not found")
        return d

    @app.get("/api/skills", response_model=list[S.SkillOut])
    def skills(db: Db, project: str | None = None, kind: str | None = None, status: str | None = None,
               q: str | None = None, unused: bool | None = None) -> list[S.SkillOut]:
        return queries.skills(db, project, kind, status, q, unused)

    @app.get("/api/skills/{sid}", response_model=S.SkillDetail)
    def skill(sid: str, db: Db, project: str | None = None) -> S.SkillDetail:
        d = queries.skill_detail(db, sid, project)
        if d is None:
            raise HTTPException(404, "skill not found")
        return d

    @app.get("/api/projects/{pid}/policies", response_model=list[S.PolicyOut])
    def policies(pid: str, db: Db) -> list[S.PolicyOut]:
        project_or_404(db, pid)
        return queries.policies(db, pid)

    @app.get("/api/projects/{pid}/audit", response_model=S.AuditPage)
    def audit_list(pid: str, type: str | None = None, actor: str | None = None, session: str | None = None,
                   date_from: str | None = Query(None, alias="from"), date_to: str | None = Query(None, alias="to"),
                   q: str | None = None, page: int = Query(1, ge=1)) -> S.AuditPage:
        size = 50
        items = audit.query(project_id=pid, type_=type, actor=actor, session=session, date_from=date_from, date_to=date_to,
                            q=q, limit=size, offset=(page - 1) * size)
        return S.AuditPage(page=page, page_size=size, items=[S.AuditEventOut(**e) for e in items])

    @app.get("/api/audit/verify", response_model=S.VerifyOut)
    def audit_verify() -> S.VerifyOut:
        state["v"] = _verify()
        return state["v"]

    @app.get("/api/settings", response_model=S.SettingsOut)
    def settings(db: Db) -> S.SettingsOut:
        cfg = config.load()
        t = pricing.table()
        versions = sorted({v for (v,) in db.execute(select(Session.tool_version).where(Session.tool_version.is_not(None)))})
        return S.SettingsOut(user=cfg["user"], memory=cfg["memory"], skills=cfg["skills"], audit=cfg["audit"], pii=cfg["pii"],
                             sync=cfg["sync"], prices={"version": t["version"], "verified": t.get("verified", False),
                                                       "source": t.get("source"), "models": t["models"]},
                             tools=[{"id": "claude-code", "name": "Claude Code", "versions": versions, "connected": bool(versions)}],
                             local_data={"home": paths.redact_home(str(paths.home())), "ledger": paths.redact_home(str(paths.ledger_db())),
                                         "audit": paths.redact_home(str(paths.audit_db())), "spool": paths.redact_home(str(paths.home() / "spool"))})

    from . import writes

    writes.register(app, state)

    if web_dist and web_dist.is_dir():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            f = (web_dist / path).resolve()
            if path and f.is_file() and web_dist.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(web_dist / "index.html")

    return app


def default_web_dist() -> Path | None:
    env = os.environ.get("SEEN_WEB_DIST")
    for cand in ([Path(env)] if env else []) + [Path(__file__).parent / "web", Path(__file__).resolve().parents[4] / "web" / "dist"]:
        if (cand / "index.html").exists():
            return cand
    return None
