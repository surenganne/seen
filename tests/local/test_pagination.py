from fastapi.testclient import TestClient

PID = "demo-payments"


def test_changes_are_paged_with_totals_across_pages(client: TestClient) -> None:
    p1 = client.get(f"/api/projects/{PID}/changes").json()
    assert p1["page"] == 1 and p1["page_size"] == 50 and p1["total"] > 50 and len(p1["items"]) == 50
    p2 = client.get(f"/api/projects/{PID}/changes", params={"page": 2}).json()
    assert len(p2["items"]) == p1["total"] - 50
    assert not {c["id"] for c in p1["items"]} & {c["id"] for c in p2["items"]}
    every = p1["items"] + p2["items"]
    assert abs(p1["cost_usd"] - sum(c["cost_usd"] for c in every)) < 0.01  # header cost covers every page
    assert client.get(f"/api/projects/{PID}/changes", params={"page": 99}).json()["items"] == []
    assert client.get(f"/api/projects/{PID}/changes", params={"page_size": 500}).status_code == 422
    assert client.get(f"/api/projects/{PID}/changes", params={"page": 0}).status_code == 422


def test_changes_filter_by_session(client: TestClient) -> None:
    sid = client.get(f"/api/projects/{PID}/changes").json()["items"][0]["session_id"]
    r = client.get(f"/api/projects/{PID}/changes", params={"session": sid}).json()
    assert r["total"] >= 1 and {c["session_id"] for c in r["items"]} == {sid}


def test_sessions_are_paged(client: TestClient) -> None:
    r = client.get(f"/api/projects/{PID}/sessions", params={"page_size": 5}).json()
    assert r["page"] == 1 and r["page_size"] == 5 and len(r["items"]) == 5 and r["total"] > 5
    assert r["active"] == sum(1 for s in client.get(f"/api/projects/{PID}/sessions", params={"page_size": 200}).json()["items"]
                              if s["status"] == "active")
