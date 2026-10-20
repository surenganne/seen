"""Every POST, PUT and DELETE route writes at least one audit event (11A rule 3)."""

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from seen_core import audit

PID = "demo-payments"
BODIES = {
    ("PUT", "/api/settings"): {"pii": {"mode": "warn"}},
    ("POST", "/api/audit/export"): {"project": PID, "format": "ndjson"},
}


def concrete(path: str, client: TestClient) -> str:
    finding = client.get(f"/api/projects/{PID}/pii").json()["items"][0]["id"] if "{finding_id}" in path else ""
    return (path.replace("{pid}", PID).replace("{sid}", "release-notes").replace("{finding_id}", finding)
            .replace("{cid}", "x"))


def test_every_state_changing_route_writes_audit(client: TestClient) -> None:
    routes = [r for r in client.app.routes if isinstance(r, APIRoute) and r.methods & {"POST", "PUT", "DELETE"}]
    assert routes, "no write routes registered"
    for r in routes:
        for m in r.methods & {"POST", "PUT", "DELETE"}:
            before = audit.verify().count
            path = concrete(r.path, client)
            resp = client.request(m, path, json=BODIES.get((m, r.path), {}), params={"project": PID}, headers={"X-Seen-Request": "1"})
            assert resp.status_code < 300, (m, path, resp.text)
            assert audit.verify().count > before, f"{m} {r.path} wrote no audit event"
