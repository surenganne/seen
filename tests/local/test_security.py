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
