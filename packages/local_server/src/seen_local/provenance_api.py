"""Read routes for AI provenance (spec 7.2): per-file blocks and the range report.

Paths and refs are untrusted input: `blame.resolve_path` and `blame.REV` refuse the unsafe ones (422), never echoed raw.
No route returns line text, and a failed or missing file is a 404, never a 500."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session as DB

from seen_core.db.models import Project
from seen_core.headline import clean
from seen_core.provenance import blame, enrich
from seen_core.provenance import report as rp

from . import schemas as S
from .app import get_db

BUDGET_S = 5.0  # wall-clock budget per file; over it the answer is truncated
Db = Annotated[DB, Depends(get_db)]
MAX_REV, MAX_PATH = 200, 4096


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
