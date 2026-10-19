from fastapi.testclient import TestClient


def test_rebound_host_rejected(client: TestClient) -> None:
    assert client.get("/api/projects", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/projects", headers={"Host": "127.0.0.1:47821"}).status_code == 200
    assert client.get("/api/projects", headers={"Host": "localhost:47821"}).status_code == 200


def test_security_headers(client: TestClient) -> None:
    h = client.get("/api/projects", headers={"Host": "localhost"}).headers
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    csp = h["content-security-policy"]
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp and "script-src 'self'" in csp
    assert h["referrer-policy"] == "no-referrer" and "camera=()" in h["permissions-policy"]
    assert "server" not in {k.lower() for k in h} or h.get("server") != "uvicorn"


def test_state_change_needs_seen_header(client: TestClient) -> None:
    r = client.put("/api/settings", json={"pii": {"mode": "warn"}}, headers={"Host": "localhost"})
    assert r.status_code == 403


def test_testserver_host_not_allowed(client: TestClient) -> None:
    assert client.get("/api/projects", headers={"Host": "testserver"}).status_code == 400


def test_free_text_settings_not_logged_raw(client: TestClient) -> None:
    import json

    from seen_core import audit

    h = {"Host": "localhost", "X-Seen-Request": "1"}
    r = client.put("/api/settings", json={"user": {"id": "dev.person@corp.test"},
                                          "sync": {"server": "https://u:SECRETPW@team.example"}, "pii": {"mode": "warn"}}, headers=h)
    assert r.status_code == 200
    blob = json.dumps(audit.query(type_="config.changed"))
    assert "dev.person" not in blob and "SECRETPW" not in blob
    pii = next(e for e in audit.query(type_="config.changed") if e["subject"] == "pii.mode")
    assert pii["detail"]["new"] == "warn"


def test_settings_validation(client: TestClient) -> None:
    h = {"Host": "localhost", "X-Seen-Request": "1"}
    assert client.put("/api/settings", json={"pii": {"mode": "yolo"}}, headers=h).status_code == 422
    assert client.put("/api/settings", json={"audit": {"retention_days": -1}}, headers=h).status_code == 422
    assert client.put("/api/settings", json={"pii": {"nope": True}}, headers=h).status_code == 422


def test_export_project_cannot_escape_exports_dir(client: TestClient, seeded) -> None:  # type: ignore[no-untyped-def]
    h = {"X-Seen-Request": "1"}
    for bad in ("x/../../../escape", "../escape", "a\\b", "", "x" * 200):
        r = client.post("/api/audit/export", json={"project": bad, "format": "csv"}, headers=h)
        assert r.status_code == 422, (bad, r.status_code)
    assert not list(seeded.rglob("escape*"))
    assert client.post("/api/audit/export", json={"project": "demo-payments"}, headers=h).status_code == 200
