"""Read routes for AI provenance (spec 7.2): per-file blocks and the range report.

Paths and refs are untrusted input: `blame.resolve_path` and `blame.REV` refuse the unsafe ones (422), never echoed raw.
No route returns line text, and a failed or missing file is a 404, never a 500."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session as DB

from seen_core.db.models import Project
from seen_core.headline import clean
from seen_core.provenance import blame, enrich
from seen_core.provenance import report as rp

from . import queries
from . import schemas as S
from .app import get_db

BUDGET_S = 5.0  # wall-clock budget per file; over it the answer is truncated
Db = Annotated[DB, Depends(get_db)]
MAX_REV, MAX_PATH, MAX_Q = 200, 4096, 200
# files sorted by: recent (newest change first), most requests, most lines (added + removed); ties by path
FILE_SORTS = {"recent": lambda r: r.last_changed_at or "", "requests": lambda r: r.requests, "lines": lambda r: r.added + r.removed}


def _ref(value: str) -> str:
    if len(value) > MAX_REV or not blame.REV.fullmatch(value):  # checked here, not by Query: its 422 echoes the input
        raise HTTPException(422, "unsafe revision")
    return value


def register(app: FastAPI, project_or_404: Callable[[DB, str], Project]) -> None:
    def repo_project(db: DB, pid: str) -> Project:
        p = project_or_404(db, pid)
        if not p.root_path or not Path(p.root_path).is_dir():
            raise HTTPException(404, "project has no repository on this machine")
        return p

    @app.get("/api/projects/{pid}/provenance/files", response_model=S.ProvenanceFiles)
    def provenance_files(pid: str, db: Db, days: int | None = Query(None, ge=1, le=3650), q: str = "", sort: str = "recent",
                         page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)) -> S.ProvenanceFiles:
        """Files your requests changed, from the ledger alone: no git and no file contents."""
        project_or_404(db, pid)
        if sort not in FILE_SORTS:  # checked here, not by Literal: its 422 echoes the input
            raise HTTPException(422, "sort must be recent, requests or lines")
        if len(q) > MAX_Q or "\x00" in q:
            raise HTTPException(422, "unsafe filter")
        by_path: dict[str, S.ProvenanceFileRow] = {}
        for r in queries.load_rows(db, pid, days):
            if r.background:
                continue
            for f in r.files:
                if q.lower() not in f.path.lower():
                    continue
                row = by_path.setdefault(f.path, S.ProvenanceFileRow(path=f.path, requests=0, added=0, removed=0,
                                                                     last_changed_at=None, last_change_id=None))
                row.requests += 1
                row.added += f.added
                row.removed += f.removed
                if (r.c.started_at or "") > (row.last_changed_at or ""):
                    row.last_changed_at, row.last_change_id = r.c.started_at, r.c.id
        rows = sorted(by_path.values(), key=lambda r: r.path)
        rows.sort(key=FILE_SORTS[sort], reverse=True)  # stable: equal keys stay in path order
        return S.ProvenanceFiles(total=len(rows), page=page, page_size=page_size,
                                 items=rows[(page - 1) * page_size: page * page_size])

    @app.get("/api/projects/{pid}/provenance/file", response_model=S.ProvenanceFile)
    def provenance_file(pid: str, db: Db, path: str, rev: str = "HEAD") -> S.ProvenanceFile:
        p = repo_project(db, pid)
        if not path or len(path) > MAX_PATH:
            raise HTTPException(422, "unsafe path")
        try:
            fp = blame.blame_file(db, p, path, _ref(rev), BUDGET_S)
        except ValueError as e:  # unsafe path or rev
            raise HTTPException(422, clean(str(e))) from e
        if blame.is_failure(fp.reason):
            raise HTTPException(404, clean(fp.reason))
        blocks = enrich.enrich_blocks(db, fp.blocks)
        return S.ProvenanceFile(path=fp.path, rev=fp.rev, counts=fp.counts, truncated=fp.truncated, reason=fp.reason,
                                blocks=[S.ProvenanceBlock(**dataclasses.asdict(b)) for b in blocks])

    @app.get("/api/projects/{pid}/provenance/range", response_model=S.ProvenanceRange)
    def provenance_range(pid: str, db: Db, base: str, head: str = "HEAD") -> S.ProvenanceRange:
        p = repo_project(db, pid)
        _ref(base), _ref(head)
        try:
            r: Any = rp.build_report(db, p, base, head)
        except ValueError as e:  # unknown ref, timeout or an unreadable diff
            raise HTTPException(404, clean(str(e))) from e
        return S.ProvenanceRange(**dataclasses.asdict(r))
