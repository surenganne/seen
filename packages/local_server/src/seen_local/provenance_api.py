"""Read routes for AI provenance (spec 7.2): per-file blocks and the range report.

Paths and refs are untrusted input: `blame.resolve_path` and `blame.REV` refuse the unsafe ones (422), never echoed raw.
No route returns line text, and a failed or missing file is a 404, never a 500."""

from __future__ import annotations

import dataclasses
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
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
REASON_NO_REPO = "no repository on this machine"  # the page matches this string: keep it stable
MAX_REV, MAX_PATH, MAX_Q = 200, 4096, 200
# files sorted by: recent (newest change first), most requests, most lines (added + removed); ties by path
FILE_SORTS = {"recent": lambda r: r.last_changed_at or "", "requests": lambda r: r.requests, "lines": lambda r: r.added + r.removed}


def _ref(value: str) -> str:
    if len(value) > MAX_REV or not blame.REV.fullmatch(value):  # checked here, not by Query: its 422 echoes the input
        raise HTTPException(422, "unsafe revision")
    return value


def _int(value: str | None, name: str, lo: int, hi: int | None, default: int | None) -> int | None:
    """A numeric query parameter checked here, not by Query(ge/le): its 422 echoes the raw input."""
    if value is None:
        return default
    if not (value.isascii() and value.isdigit()) or len(value) > 9 or int(value) < lo or (hi is not None and int(value) > hi):
        raise HTTPException(422, f"{name} must be a whole number from {lo}{f' to {hi}' if hi else ' up'}")
    return int(value)


def register(app: FastAPI, project_or_404: Callable[[DB, str], Project]) -> None:
    def has_repo(p: Project) -> bool:
        return bool(p.root_path) and Path(p.root_path or "").is_dir()

    def repo_project(db: DB, pid: str) -> Project:
        p = project_or_404(db, pid)
        if not has_repo(p):
            raise HTTPException(404, "project has no repository on this machine")
        return p

    @app.get("/api/projects/{pid}/provenance/files", response_model=S.ProvenanceFiles)
    def provenance_files(pid: str, db: Db, days: str | None = None, q: str = "", sort: str = "recent",
                         page: str | None = None, page_size: str | None = None) -> S.ProvenanceFiles:
        """Files your requests changed, from the ledger alone: no git and no file contents."""
        project_or_404(db, pid)
        n_days, n_page, n_size = _int(days, "days", 1, 3650, None), _int(page, "page", 1, None, 1), _int(page_size, "page_size", 1, 200, 50)
        assert n_page is not None and n_size is not None
        if sort not in FILE_SORTS:  # checked here, not by Literal: its 422 echoes the input
            raise HTTPException(422, "sort must be recent, requests or lines")
        if len(q) > MAX_Q or "\x00" in q:
            raise HTTPException(422, "unsafe filter")
        by_path: dict[str, S.ProvenanceFileRow] = {}
        for r in queries.load_rows(db, pid, n_days):
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
        return S.ProvenanceFiles(total=len(rows), page=n_page, page_size=n_size,
                                 items=rows[(n_page - 1) * n_size: n_page * n_size])

    @app.get("/api/projects/{pid}/provenance/file", response_model=S.ProvenanceFile)
    def provenance_file(pid: str, db: Db, path: str, rev: str = "HEAD") -> S.ProvenanceFile:
        p = project_or_404(db, pid)
        if not path or len(path) > MAX_PATH:
            raise HTTPException(422, "unsafe path")
        if not has_repo(p):  # not an error of the request (the Docker dashboard has a ledger snapshot only): validate, then say why
            rev = _ref(rev)
            try:
                with tempfile.TemporaryDirectory() as scratch:  # the same path checks as with a repo, against an empty root
                    path = blame.resolve_path(scratch, path)
            except ValueError as e:
                raise HTTPException(422, clean(str(e))) from e
            return S.ProvenanceFile(path=path, rev=rev, counts={k: 0 for k in ("agent", "human", "not_observed", "neutral")},
                                    truncated=False, reason=REASON_NO_REPO, blocks=[])
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
