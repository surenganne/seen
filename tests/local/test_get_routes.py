"""Every GET route answers on real-shaped data (never a 500), and SPA pages answer HEAD as well as GET."""

from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

PID = "demo-payments"


def test_every_get_route_answers(client: TestClient) -> None:
    cid = client.get(f"/api/projects/{PID}/changes").json()["items"][0]["id"]
    routes = [r for r in client.app.routes if isinstance(r, APIRoute) and "GET" in r.methods]
    assert len(routes) > 10
    for r in routes:
        if r.path == "/api/team/callback":
            continue  # a redirect to the SPA /team page; covered in test_team_login.py
        path = r.path.replace("{pid}", PID).replace("{cid}", cid).replace("{sid}", "release-notes")
        resp = client.get(path, params={"project": PID})
        assert resp.status_code == 200, (path, resp.status_code, resp.text[:200])


def test_spa_pages_answer_head(seeded: Path, tmp_path: Path) -> None:
    from seen_local.app import create_app

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    c = TestClient(create_app(web_dist=dist), base_url="http://localhost")
    for path in ("/projects", f"/p/{PID}/sessions", "/"):
        assert c.get(path).status_code == 200, path
        assert c.head(path).status_code == 200, path


def test_spa_shell_is_never_cached_but_hashed_assets_are(seeded: Path, tmp_path: Path) -> None:
    """A cached index.html after an upgrade points at asset hashes that no longer exist: a blank page."""
    from seen_local.app import create_app

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)")
    c = TestClient(create_app(web_dist=dist), base_url="http://localhost")
    for path in ("/", f"/p/{PID}/sessions"):
        assert c.get(path).headers["cache-control"] == "no-cache", path
    assert "immutable" in c.get("/assets/index-abc123.js").headers["cache-control"]
