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
from seen_core.pii.checked import PII_CHECKED

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
    import sqlite3

    from seen_core import sync

    v = audit.verify()
    ok, reason, brk, note, anchored = v.ok, v.reason, v.break_seq, ANCHOR_NOTE, False
    a = sync.anchor()
    if a:
        anchored = True
        note = (f"Anchored on {a.get('server')} through seq {a['seq']} ({str(a.get('at'))[:10]}). "
                "Rewriting local history before that point is detectable.")
        try:
            con = sqlite3.connect(f"file:{paths.audit_db()}?mode=ro", uri=True)
            row = con.execute("SELECT hash FROM audit_events WHERE seq = ?", (a["seq"],)).fetchone()
            con.close()
        except sqlite3.Error:
            row = None
        if row is None or row[0] != a["hash"]:
            ok, brk = False, a["seq"]
            reason = "anchored head differs from the local chain: local history was rewritten after anchoring"
    return S.VerifyOut(ok=ok, count=v.count, head=v.head, head_seq=v.head_seq, break_seq=brk, expected=a["hash"] if a and not ok else v.expected,
                       found=v.found, reason=reason, verified_at=v.verified_at, anchored=anchored, anchor_note=note)


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
        if request.url.path.startswith("/assets/") and resp.status_code == 200:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"  # file names carry a content hash
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
                pii: bool | None = None,
                days: int | None = Query(None, ge=1, le=3650), sort: str = "time",
                dir: Literal["asc", "desc"] = "desc", session: str | None = None,
                kind: Literal["all", "yours", "background"] = "all", page: int = Query(1, ge=1),
                page_size: int = Query(50, ge=1, le=200)) -> S.ChangePage:
        project_or_404(db, pid)
        return queries.changes(db, pid, tool=tool, status=status, q=q, file=file, skill=skill, policy_missed=policy_missed,
                               pii=pii, days=days, sort=sort, dir=dir, session=session, kind=kind, page=page,
                               page_size=page_size)

    @app.get("/api/projects/{pid}/sessions", response_model=S.SessionPage)
    def sessions(pid: str, db: Db, kind: Literal["all", "yours", "background"] = "all", page: int = Query(1, ge=1),
                 page_size: int = Query(50, ge=1, le=200)) -> S.SessionPage:
        project_or_404(db, pid)
        all_ = queries.sessions(db, pid)
        bg = sum(s.background for s in all_)
        shown = all_ if kind == "all" else [s for s in all_ if s.background == (kind == "background")]
        return S.SessionPage(total=len(shown), active=sum(s.status == "active" for s in shown),
                             counts=S.SessionCounts(all=len(all_), yours=len(all_) - bg, background=bg),
                             page=page, page_size=page_size, items=shown[(page - 1) * page_size: page * page_size])

    @app.get("/api/projects/{pid}/timeline", response_model=S.TimelinePage)
    def timeline(pid: str, db: Db, actor: str | None = None, days: int | None = Query(None, ge=1, le=3650),
                 all_turns: bool = False, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)) -> S.TimelinePage:
        project_or_404(db, pid)
        return queries.timeline(db, pid, actor=actor, days=days, all_turns=all_turns, page=page, page_size=page_size)

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

    @app.get("/api/projects/{pid}/pii", response_model=S.PiiPage)
    def pii_list(pid: str, db: Db, range_: Annotated[int | None, Query(alias="range")] = None, type: str | None = None,
                 source: str | None = None, status: str | None = None) -> S.PiiPage:
        project_or_404(db, pid)
        rows = queries.load_rows(db, pid, range_)
        items = [S.PiiRow(**queries.pii_out(f).model_dump(), change_id=r.c.id, started_at=r.c.started_at, summary=r.c.summary)
                 for r in rows for f in r.pii
                 if (not type or f.type == type) and (not source or f.source_kind == source) and (not status or f.status == status)]
        return S.PiiPage(items=items, checked=PII_CHECKED)

    @app.get("/api/changes/{cid}/pii", response_model=list[S.PiiFindingOut])
    def change_pii(cid: str, db: Db) -> list[S.PiiFindingOut]:
        from seen_core.db.models import PiiFinding

        return [queries.pii_out(f) for f in db.scalars(select(PiiFinding).where(PiiFinding.change_id == cid))]

    @app.get("/api/projects/{pid}/pii/deny-snippet", response_model=S.DenySnippet)
    def deny_snippet(pid: str, db: Db) -> S.DenySnippet:
        import json as _json

        project_or_404(db, pid)
        rules = sorted({r for s_ in queries.overview(db, pid, 28, True).pii_top_sources if (r := s_.deny_rule)})
        return S.DenySnippet(rules=rules, snippet=_json.dumps({"permissions": {"deny": rules}}, indent=2),
                             note="Add to the repo's .claude/settings.json. Seen shows this and never writes it. "
                                  "A Read deny does not cover cat through Bash.")

    @app.get("/api/audit/verify", response_model=S.VerifyOut)
    def audit_verify() -> S.VerifyOut:
        state["v"] = _verify()
        return state["v"]

    @app.get("/api/settings", response_model=S.SettingsOut)
    def settings(db: Db) -> S.SettingsOut:
        cfg = config.load()
        t = pricing.table()
        versions = sorted({v for (v,) in db.execute(select(Session.tool_version).where(Session.tool_version.is_not(None)))})
        return S.SettingsOut(user=cfg["user"], skills=cfg["skills"], audit=cfg["audit"], pii=cfg["pii"],
                             sync=cfg["sync"], provenance=cfg["provenance"], prices={"version": t["version"], "verified": t.get("verified", False),
                                                       "source": t.get("source"), "models": t["models"]},
                             tools=[{"id": "claude-code", "name": "Claude Code", "versions": versions, "connected": bool(versions)}],
                             local_data={"home": paths.redact_home(str(paths.home())), "ledger": paths.redact_home(str(paths.ledger_db())),
                                         "audit": paths.redact_home(str(paths.audit_db())), "spool": paths.redact_home(str(paths.home() / "spool"))})

    from . import provenance_api, writes

    writes.register(app, state)
    provenance_api.register(app, project_or_404)

    if web_dist and web_dist.is_dir():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)  # link checkers and extensions send HEAD
        def spa(path: str) -> FileResponse:
            f = (web_dist / path).resolve()
            if path and f.is_file() and web_dist.resolve() in f.parents:
                return FileResponse(f)
            # revalidate every time: a cached shell after an upgrade points at asset hashes that are gone (blank page)
            return FileResponse(web_dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def default_web_dist() -> Path | None:
    env = os.environ.get("SEEN_WEB_DIST")
    for cand in ([Path(env)] if env else []) + [Path(__file__).parent / "web", Path(__file__).resolve().parents[4] / "web" / "dist"]:
        if (cand / "index.html").exists():
            return cand
    return None
