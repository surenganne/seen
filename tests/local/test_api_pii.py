from fastapi.testclient import TestClient

from seen_core import audit

PID = "demo-patient"
H = {"X-Seen-Request": "1"}


def test_project_pii_list_and_filters(client: TestClient) -> None:
    r = client.get(f"/api/projects/{PID}/pii", params={"range": 28}).json()
    assert r["items"] and {"id", "type", "count", "source_ref", "destination", "status", "change_id"} <= set(r["items"][0])
    assert "fingerprints" not in r["items"][0] and "fingerprints_json" not in r["items"][0]
    t = r["items"][0]["type"]
    assert all(i["type"] == t for i in client.get(f"/api/projects/{PID}/pii", params={"type": t}).json()["items"])
    src = client.get(f"/api/projects/{PID}/pii", params={"source": "file_read"}).json()["items"]
    assert all(i["source_kind"] == "file_read" for i in src)
    assert r["checked"] and "not detected" in r["checked"]


def test_change_pii_endpoint(client: TestClient) -> None:
    f = client.get(f"/api/projects/{PID}/pii").json()["items"][0]
    items = client.get(f"/api/changes/{f['change_id']}/pii").json()
    assert any(i["id"] == f["id"] for i in items)


def test_mark_test_data_updates_counts_and_audits(client: TestClient) -> None:
    f = next(i for i in client.get(f"/api/projects/{PID}/pii").json()["items"] if i["status"] == "open")
    before = client.get(f"/api/changes/{f['change_id']}").json()
    r = client.post(f"/api/pii/{f['id']}/mark-test-data", headers=H)
    assert r.status_code == 200
    after = client.get(f"/api/changes/{f['change_id']}").json()
    assert next(p for p in after["pii"] if p["id"] == f["id"])["status"] == "test_data"
    rows = {c["id"]: c for c in client.get(f"/api/projects/{PID}/changes").json()["items"]}
    assert rows[f["change_id"]]["pii_count"] == sum(p["count"] for p in before["pii"] if p["status"] == "open") - f["count"]
    ev = audit.query(type_="approval.pii_test_data")[0]
    assert ev["subject"] == f["id"] and ev["actor_id"] and ev["detail"]["old"] == "open" and ev["detail"]["new"] == "test_data"
    assert client.post("/api/pii/nope/mark-test-data", headers=H).status_code == 404


def test_deny_snippet(client: TestClient) -> None:
    r = client.get(f"/api/projects/{PID}/pii/deny-snippet").json()
    assert "Read(./data/patients.csv)" in r["rules"]
    assert '"deny"' in r["snippet"] and "Bash" in r["note"]
