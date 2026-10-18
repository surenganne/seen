from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seen_core import devseed


@pytest.fixture
def seeded(seen_home: Path) -> Path:
    devseed.seed(seen_home)
    return seen_home


@pytest.fixture
def client(seeded: Path) -> TestClient:
    from seen_local.app import create_app

    return TestClient(create_app(web_dist=None))
