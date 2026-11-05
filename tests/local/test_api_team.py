"""/api/team/projects*: the dashboard's proxy to the team server. Always 200 with a state; the key never leaves the process."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from seen_core import paths
from seen_local import team

KEY = "sentinel-" + "z" * 40
URL = "http://127.0.0.1:9"
H = {"Host": "localhost"}
STATES = ["not_configured", "login_required", "unauthorized", "forbidden", "unreachable", "bad_response", "ok"]

PROJECTS = [{"id": "p1", "name": "p1", "changes": 3, "last_change_at": "2026-11-01T00:00:00Z", "cost_7d": 1.5, "secret": "x"}]
OVERVIEW = {"range": 7, "tiles": {"changes": 2, "lines_added": 5, "lines_removed": 1, "cost_usd": 0.5, "policy_missed": 1, "pii_changes": 0},
            "cost_by_day": [{"date": "2026-11-01", "by_tool": {"claude-code": 0.5}}], "top_skills": [{"skill_id": "s", "runs": 2}],
            "by_model": [{"model": "m", "changes": 2, "tok_out": 9, "cost_usd": 0.5}], "pii_by_type": [{"type": "email", "count": 1}],
            "leak": "x"}
MEMBERS = [{"user_id": "u1", "email": "a@b.c", "last_synced_at": None, "changes": 4, "key_expired": False, "key_id": "k"}]


@pytest.fixture
def setup(seeded: Path, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    paths.config_toml().write_text(f'[sync]\nenabled = true\nserver = "{URL}"\n')
    monkeypatch.setenv("SEEN_TEAM_API_KEY", KEY)
    return []


def reply(monkeypatch: pytest.MonkeyPatch, status: int, body: Any) -> list[Any]:
    seen: list[Any] = []
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    monkeypatch.setattr(team, "_open", lambda req: (seen.append(req), (status, raw))[1])
    return seen


def test_projects_ok_maps_body(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = reply(monkeypatch, 200, PROJECTS)
    r = client.get("/api/team/projects", headers=H)
    assert r.status_code == 200 and r.json() == {"state": "ok", "reason": None, "projects": [
        {"id": "p1", "name": "p1", "changes": 3, "last_change_at": "2026-11-01T00:00:00Z", "cost_7d": 1.5}]}
    assert seen[0].full_url == f"{URL}/api/projects"


def test_empty_projects_for_member_is_ok(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    reply(monkeypatch, 200, [])
    assert client.get("/api/team/projects", headers=H).json() == {"state": "ok", "reason": None, "projects": []}


def test_overview_ok_maps_tiles_and_lists(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = reply(monkeypatch, 200, OVERVIEW)
    j = client.get("/api/team/projects/p1/overview?range=14", headers=H).json()
    assert j["state"] == "ok" and j["tiles"]["policy_missed"] == 1 and j["top_skills"] == [{"skill_id": "s", "runs": 2}]
    assert j["pii_by_type"] == [{"type": "email", "count": 1}] and "leak" not in j
    assert seen[0].full_url == f"{URL}/api/projects/p1/overview?range=14"


def test_not_configured_is_200_with_reason(client: TestClient, seeded: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEEN_TEAM_API_KEY", raising=False)
    for url in ("/api/team/projects", "/api/team/projects/p1/overview", "/api/team/projects/p1/members"):
        j = client.get(url, headers=H).json()
        assert j["state"] == "not_configured" and j["reason"] == team.REASONS["not_configured"]
    assert client.get("/api/team/projects/p1/overview", headers=H).json()["tiles"] is None


@pytest.mark.parametrize("status,body,state", [(401, {}, "unauthorized"), (403, {}, "forbidden"), (500, {}, "unreachable"),
                                               (200, {"nope": 1}, "bad_response"), (200, b"junk", "bad_response")])
def test_each_team_failure_is_200_with_state(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch,
                                             status: int, body: Any, state: str) -> None:
    reply(monkeypatch, status, body)
    for url in ("/api/team/projects", "/api/team/projects/p1/overview", "/api/team/projects/p1/members"):
        r = client.get(url, headers=H)
        assert r.status_code == 200 and r.json()["state"] == state and r.json()["reason"] == team.REASONS[state], url


def test_wrong_top_level_type_is_bad_response(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    reply(monkeypatch, 200, {"projects": []})
    assert client.get("/api/team/projects", headers=H).json()["state"] == "bad_response"
    reply(monkeypatch, 200, [])
    assert client.get("/api/team/projects/p1/overview", headers=H).json()["state"] == "bad_response"
    reply(monkeypatch, 200, [{"user_id": 5}])
    assert client.get("/api/team/projects/p1/members", headers=H).json()["state"] == "bad_response"


BAD_PIDS = ["..%2Fkeys", "a%2Fb", "x%3Fy%3D1", "a" * 65, "%2E%2E", "a%23b", "a%20b"]


@pytest.mark.parametrize("pid", BAD_PIDS)
@pytest.mark.parametrize("tail", ["overview", "members"])
def test_pid_is_validated_before_any_request(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch, pid: str, tail: str) -> None:
    seen = reply(monkeypatch, 200, {})
    r = client.get(f"/api/team/projects/{pid}/{tail}", headers=H)
    assert r.status_code in (404, 422) and not seen
    if "%2F" not in pid and "%2E" not in pid:  # an id with a slash matches no route (404); a bare .. is normalised by the client
        assert r.status_code == 422


def test_dot_pid_is_rejected(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = reply(monkeypatch, 200, {})
    assert client.get("/api/team/projects/./members", headers=H).status_code in (404, 422) and not seen


def test_pid_is_quoted_outbound(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = reply(monkeypatch, 200, MEMBERS)
    assert client.get("/api/team/projects/a:b.c_d-1/members", headers=H).json()["state"] == "ok"
    assert seen[0].full_url == f"{URL}/api/projects/a%3Ab.c_d-1/members"


def test_members_ok_maps_body_and_drops_extra_fields(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    reply(monkeypatch, 200, MEMBERS)
    assert client.get("/api/team/projects/p1/members", headers=H).json() == {"state": "ok", "reason": None, "members": [
        {"user_id": "u1", "email": "a@b.c", "last_synced_at": None, "changes": 4, "key_expired": False}]}


def test_members_forbidden_state_for_member_key(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    reply(monkeypatch, 403, {"detail": "only leads and admins can list members"})
    j = client.get("/api/team/projects/p1/members", headers=H).json()
    assert j["state"] == "forbidden" and j["members"] == [] and "leads" not in json.dumps(j)


@pytest.mark.parametrize("rng", ["0", "8", "30", "x", "-7"])
def test_range_must_be_7_14_28(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch, rng: str) -> None:
    seen = reply(monkeypatch, 200, OVERVIEW)
    assert client.get(f"/api/team/projects/p1/overview?range={rng}", headers=H).status_code == 422 and not seen


def test_extra_team_fields_are_dropped_not_forwarded(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    reply(monkeypatch, 200, PROJECTS)
    assert "secret" not in client.get("/api/team/projects", headers=H).text


def serve(monkeypatch: pytest.MonkeyPatch, status: int, bodies: dict[str, Any] | bytes) -> None:
    def op(req: Any) -> tuple[int, bytes]:
        if isinstance(bodies, bytes):
            return status, bodies
        tail = req.full_url.split("?")[0].rsplit("/", 1)[-1]
        return status, json.dumps(bodies["projects" if tail == "projects" else tail]).encode()

    monkeypatch.setattr(team, "_open", op)


@pytest.mark.parametrize("state", STATES)
def test_key_never_in_any_response(client: TestClient, seeded: Path, monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    monkeypatch.setenv("SEEN_TEAM_API_KEY", KEY)
    paths.config_toml().write_text(f'[sync]\nenabled = true\nserver = "{URL}"\n')
    if state == "not_configured":
        paths.config_toml().write_text("[sync]\nenabled = true\n")
    elif state == "login_required":
        monkeypatch.delenv("SEEN_TEAM_API_KEY")
    elif state == "ok":
        serve(monkeypatch, 200, {"projects": PROJECTS, "overview": OVERVIEW, "members": MEMBERS})
    else:
        status = {"unauthorized": 401, "forbidden": 403, "unreachable": 500}.get(state, 200)
        serve(monkeypatch, status, b"junk" if state == "bad_response" else json.dumps({"detail": KEY + URL}).encode())
    for url in ("/api/team/projects", "/api/team/projects/p1/overview", "/api/team/projects/p1/members"):
        r = client.get(url, headers=H)
        assert r.status_code == 200 and r.json()["state"] == state, (url, r.text)
        assert KEY not in r.text and URL not in r.text
        assert not {"authorization", "set-cookie"} & {k.lower() for k in r.headers}


@pytest.mark.parametrize("pid", ["abc%0A", "a" * 64 + "%0A", "a..b", "..x", "x.."])
@pytest.mark.parametrize("tail", ["overview", "members"])
def test_newline_and_dotdot_pids_are_422(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch, pid: str, tail: str) -> None:
    seen = reply(monkeypatch, 200, {})
    assert client.get(f"/api/team/projects/{pid}/{tail}", headers=H).status_code == 422 and not seen


def test_pid_helper_rejects_dot_ids() -> None:
    from fastapi import HTTPException

    from seen_local.team_api import _pid

    for bad in (".", "..", "a..b", "abc\n", ""):
        with pytest.raises(HTTPException) as e:
            _pid(bad)
        assert e.value.status_code == 422
    assert _pid("a:b") == "a%3Ab"


def _ov(**tiles: Any) -> dict[str, Any]:
    o = json.loads(json.dumps(OVERVIEW))
    o["tiles"].update(tiles)
    return o


@pytest.mark.parametrize("raw", [
    b'[{"id":"p","name":"p","changes":1,"last_change_at":null,"cost_7d":%s}]' % v for v in (b"NaN", b"Infinity", b"-Infinity", b"1e999")])
def test_nonfinite_projects_cost_is_bad_response(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch, raw: bytes) -> None:
    reply(monkeypatch, 200, raw)
    r = client.get("/api/team/projects", headers=H)
    assert r.status_code == 200 and r.json()["state"] == "bad_response"


@pytest.mark.parametrize("v", ["NaN", "Infinity", "1e999"])
def test_nonfinite_overview_floats_are_bad_response(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch, v: str) -> None:
    base = json.dumps(OVERVIEW)
    for old in ('"cost_usd": 0.5, "policy_missed"', '"claude-code": 0.5', '"tok_out": 9, "cost_usd": 0.5'):
        assert old in base
        reply(monkeypatch, 200, base.replace(old, old.replace("0.5", v)).encode())
        r = client.get("/api/team/projects/p1/overview", headers=H)
        assert r.status_code == 200 and r.json()["state"] == "bad_response", old


@pytest.mark.parametrize("path,body", [
    ("overview", lambda: _ov(changes="5")), ("overview", lambda: _ov(changes=True)), ("overview", lambda: _ov(cost_usd="1.5")),
    ("overview", lambda: {**OVERVIEW, "range": "7"}), ("overview", lambda: {k: v for k, v in OVERVIEW.items() if k != "tiles"}),
    ("overview", lambda: {**OVERVIEW, "top_skills": [{"skill_id": None, "runs": 1}]}),
    ("members", lambda: [{**MEMBERS[0], "key_expired": 1}]), ("members", lambda: [{**MEMBERS[0], "changes": "4"}]),
    ("members", lambda: [{k: v for k, v in MEMBERS[0].items() if k != "user_id"}]),
    ("members", lambda: [{**MEMBERS[0], "user_id": None}]),
    ("members", lambda: [{**MEMBERS[0], "user_id": 5}]),
])
def test_wrong_typed_values_are_bad_response(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch, path: str, body: Any) -> None:
    reply(monkeypatch, 200, body())
    assert client.get(f"/api/team/projects/p1/{path}", headers=H).json()["state"] == "bad_response"


def test_projects_wrong_types_and_int_money_ok(client: TestClient, setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    reply(monkeypatch, 200, [{**PROJECTS[0], "cost_7d": 2}])
    j = client.get("/api/team/projects", headers=H).json()
    assert j["state"] == "ok" and j["projects"][0]["cost_7d"] == 2
    for bad in ({"changes": "3"}, {"cost_7d": "1.5"}, {"name": None}, {"changes": True}):
        reply(monkeypatch, 200, [{**PROJECTS[0], **bad}])
        assert client.get("/api/team/projects", headers=H).json()["state"] == "bad_response", bad


def test_post_is_rejected(client: TestClient, setup: Any) -> None:
    for url in ("/api/team/projects", "/api/team/projects/p1/overview", "/api/team/projects/p1/members"):
        assert client.post(url, headers=H).status_code == 403  # missing X-Seen-Request
        assert client.post(url, headers={**H, "X-Seen-Request": "1"}).status_code == 405
