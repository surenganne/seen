import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

BOOT = "boot-" + "k" * 40


@pytest.fixture(autouse=True)
def _dispose_engines(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every create_app opens its own connection pool. Without this the Postgres suite keeps hundreds of them alive until
    garbage collection and the server answers "too many clients already"."""
    import sqlalchemy as sa

    made: list[sa.Engine] = []
    real = sa.create_engine

    def tracked(*a: Any, **k: Any) -> sa.Engine:
        e = real(*a, **k)
        made.append(e)
        return e

    monkeypatch.setattr(sa, "create_engine", tracked)
    yield
    for e in made:
        e.dispose()


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
