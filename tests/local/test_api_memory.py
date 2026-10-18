from fastapi.testclient import TestClient

from seen_core import audit

PID = "demo-payments"
H = {"X-Seen-Request": "1"}


def test_memory_list_and_filters(client: TestClient) -> None:
    r = client.get(f"/api/projects/{PID}/memory").json()
    items = r["items"]
    assert items and {"id", "type", "status", "scope", "file_ref", "verified_at", "body", "used_in"} <= set(items[0])
    assert {i["status"] for i in items} >= {"unverified"}
    only = client.get(f"/api/projects/{PID}/memory", params={"status": "unverified"}).json()["items"]
    assert only and all(i["status"] == "unverified" for i in only)
    t = client.get(f"/api/projects/{PID}/memory", params={"type": "decision"}).json()["items"]
    assert all(i["type"] == "decision" for i in t)
    q = client.get(f"/api/projects/{PID}/memory", params={"q": "idempotency"}).json()["items"]
    assert q and all("idempotency" in (i["body"] + i["id"]).lower() for i in q)


def test_seeded_memory_is_stale_and_reverify_clears(client: TestClient) -> None:
    items = client.get(f"/api/projects/{PID}/memory").json()["items"]
    stale = [i for i in items if i["status"] == "stale"]
    assert stale and stale[0]["stale_reason"]
    mid = stale[0]["id"]
    r = client.post(f"/api/memory/{mid}/verify", params={"project": PID}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "verified"
    assert next(i for i in client.get(f"/api/projects/{PID}/memory").json()["items"] if i["id"] == mid)["status"] == "verified"
    ev = audit.query(type_="approval.memory_verified")
    assert ev[0]["subject"] == mid and ev[0]["detail"]["old"] == "stale"


def test_archive_removes_from_list(client: TestClient) -> None:
    mid = client.get(f"/api/projects/{PID}/memory").json()["items"][0]["id"]
    assert client.post(f"/api/memory/{mid}/archive", params={"project": PID}, headers=H).status_code == 200
    assert mid not in {i["id"] for i in client.get(f"/api/projects/{PID}/memory").json()["items"]}
    assert audit.query(type_="approval.memory_archived")


def test_unknown_memory_404(client: TestClient) -> None:
    assert client.post("/api/memory/nope/verify", params={"project": PID}, headers=H).status_code == 404
