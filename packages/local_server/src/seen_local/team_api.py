"""Read-only proxy routes for the team dashboard. Every team state is a 200 with a fixed reason; the key never leaves team.py."""

from __future__ import annotations

import re
import urllib.parse
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Path, Query
from pydantic import TypeAdapter, ValidationError

from . import schemas as S
from . import team

PID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def _pid(pid: str) -> str:
    if not PID.match(pid) or pid in (".", ".."):
        raise HTTPException(422, "invalid project id")
    return urllib.parse.quote(pid, safe="")


def _parse(r: team.TeamResult, tp: type[Any]) -> Any:
    """The validated body, or None (-> bad_response). Never echoes the body or the error."""
    try:
        return TypeAdapter(tp).validate_python(r.body)
    except ValidationError:
        return None


def register(app: FastAPI) -> None:
    @app.get("/api/team/projects", response_model=S.TeamProjects)
    def team_projects() -> S.TeamProjects:
        r = team.fetch("/api/projects")
        if r.state != "ok":
            return S.TeamProjects(state=r.state, reason=r.reason)
        rows = _parse(r, list[S.TeamProjectOut])
        if rows is None:
            return S.TeamProjects(state="bad_response", reason=team.REASONS["bad_response"])
        return S.TeamProjects(state="ok", reason=None, projects=rows)

    @app.get("/api/team/projects/{pid}/overview", response_model=S.TeamOverviewOut)
    def team_overview(pid: Annotated[str, Path()], range_: Annotated[int, Query(alias="range", description="7, 14 or 28 days")] = 7) -> S.TeamOverviewOut:
        q = _pid(pid)
        if range_ not in (7, 14, 28):
            raise HTTPException(422, "range must be 7, 14 or 28")
        r = team.fetch(f"/api/projects/{q}/overview", {"range": range_})
        if r.state != "ok":
            return S.TeamOverviewOut(state=r.state, reason=r.reason)
        d = _parse(r, S.TeamOverviewData)
        if d is None:
            return S.TeamOverviewOut(state="bad_response", reason=team.REASONS["bad_response"])
        return S.TeamOverviewOut(state="ok", reason=None, **d.model_dump())

    @app.get("/api/team/projects/{pid}/members", response_model=S.TeamMembers)
    def team_members(pid: Annotated[str, Path()]) -> S.TeamMembers:
        r = team.fetch(f"/api/projects/{_pid(pid)}/members")
        if r.state != "ok":
            return S.TeamMembers(state=r.state, reason=r.reason)
        rows = _parse(r, list[S.TeamMemberOut])
        if rows is None:
            return S.TeamMembers(state="bad_response", reason=team.REASONS["bad_response"])
        return S.TeamMembers(state="ok", reason=None, members=rows)
