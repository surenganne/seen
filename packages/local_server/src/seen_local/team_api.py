"""Read-only proxy routes for the team dashboard. Every team state is a 200 with a fixed reason; the key never leaves team.py."""

from __future__ import annotations

import re
import urllib.parse
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Path, Query
from pydantic import TypeAdapter, ValidationError

from . import schemas as S
from . import team

PID = re.compile(r"[A-Za-z0-9_.:-]{1,64}")


def _pid(pid: str) -> str:
    if not PID.fullmatch(pid) or ".." in pid or pid == ".":
        raise HTTPException(422, "invalid project id")
    return urllib.parse.quote(pid, safe="")


def _parse(r: team.TeamResult, tp: type[Any]) -> Any:
    """The validated body, or None (-> bad_response). Never echoes the body or the error."""
    try:
        return TypeAdapter(tp).validate_python(r.body)
    except ValidationError:
        return None


def register(app: FastAPI, remote: bool = False) -> None:
    """remote: the dashboard is reachable beyond this machine; it never reads team data on the owner's key."""
    @app.get("/api/team/sso", response_model=S.TeamSso)
    def team_sso() -> S.TeamSso:
        """Is SSO set up on the team server, and (for a signed-in admin) with what settings. Fixed reasons, no server text."""
        if remote:
            return S.TeamSso(state="not_configured", reason=team.REASONS["not_configured"])
        pub = team.fetch_public("/auth/config")
        if pub.state != "ok":
            return S.TeamSso(state=pub.state, reason=team.REASONS[pub.state])
        if pub.status == 503:
            detail = pub.body.get("detail") if isinstance(pub.body, dict) else None
            if detail == "SSO is not configured":
                return S.TeamSso(state="ok", sso="off")
            return S.TeamSso(state="ok", sso="provider_unavailable")
        b = pub.body
        client_id = b.get("client_id") if pub.status == 200 and isinstance(b, dict) else None
        endpoint = b.get("authorization_endpoint") if isinstance(b, dict) else None
        host = urllib.parse.urlparse(endpoint).hostname if isinstance(endpoint, str) else None
        if not (isinstance(client_id, str) and 0 < len(client_id) <= 200 and host):
            return S.TeamSso(state="bad_response", reason=team.REASONS["bad_response"])
        out = S.TeamSso(state="ok", sso="configured", client_id=client_id, provider_host=host[:200])
        r = team.fetch("/api/sso")  # an admin key shows the server's settings; anyone else just gets the public status
        if r.state == "ok":
            out.server = _parse(r, S.TeamSsoServer)
        return out

    @app.get("/api/team/projects", response_model=S.TeamProjects)
    def team_projects() -> S.TeamProjects:
        if remote:
            return S.TeamProjects(state="not_configured", reason=team.REASONS["not_configured"])
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
        if remote:
            return S.TeamOverviewOut(state="not_configured", reason=team.REASONS["not_configured"])
        r = team.fetch(f"/api/projects/{q}/overview", {"range": range_})
        if r.state != "ok":
            return S.TeamOverviewOut(state=r.state, reason=r.reason)
        d = _parse(r, S.TeamOverviewData)
        if d is None:
            return S.TeamOverviewOut(state="bad_response", reason=team.REASONS["bad_response"])
        return S.TeamOverviewOut(state="ok", reason=None, **d.model_dump())

    @app.get("/api/team/projects/{pid}/members", response_model=S.TeamMembers)
    def team_members(pid: Annotated[str, Path()]) -> S.TeamMembers:
        q = _pid(pid)
        if remote:
            return S.TeamMembers(state="not_configured", reason=team.REASONS["not_configured"])
        r = team.fetch(f"/api/projects/{q}/members")
        if r.state != "ok":
            return S.TeamMembers(state=r.state, reason=r.reason)
        rows = _parse(r, list[S.TeamMemberOut])
        if rows is None:
            return S.TeamMembers(state="bad_response", reason=team.REASONS["bad_response"])
        return S.TeamMembers(state="ok", reason=None, members=rows)
