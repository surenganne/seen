import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BOOT = "boot-" + "k" * 40


@pytest.fixture
def team_url(tmp_path: Path) -> str:
    # pg tests set SEEN_TEAM_TEST_URL to the dockerised test database; otherwise a throwaway SQLite file
    return os.environ.get("SEEN_TEAM_TEST_URL") or f"sqlite:///{tmp_path / 'team.db'}"


@pytest.fixture
def team(team_url: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from seen_team.app import create_app

    monkeypatch.setenv("SEEN_TEAM_BOOTSTRAP_KEY", BOOT)
    app = create_app(team_url, reset=True)
    return TestClient(app, base_url="http://localhost")


def admin(c: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {BOOT}"}


def make_key(c: TestClient, project: str | None, role: str, user: str | None = "u_a") -> str:
    body = {"project_id": project, "role": role, "user_id": user if role == "member" else None}
    r = c.post("/api/keys", json=body, headers=admin(c))
    assert r.status_code == 200, r.text
    return r.json()["key"]
