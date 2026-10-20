from fastapi.testclient import TestClient

PID = "demo-payments"


def test_timeline_groups_changes_by_day_newest_first(client: TestClient) -> None:
    t = client.get(f"/api/projects/{PID}/timeline", params={"page_size": 200}).json()
    flat = [e for d in t["days"] for e in d["entries"]]
    assert t["total"] == len(flat) > 10
    assert [d["day"] for d in t["days"]] == sorted((d["day"] for d in t["days"]), reverse=True)
    for d in t["days"]:
        times = [e["started_at"] for e in d["entries"]]
        assert times == sorted(times, reverse=True)
    assert flat[0]["actor"] == "u_demo" and "u_demo" in t["actors"]
    assert {"request", "summary", "files", "added", "removed", "git_status", "session_id"} <= set(flat[0])


def test_timeline_filters_and_paging(client: TestClient) -> None:
    some = client.get(f"/api/projects/{PID}/timeline", params={"actor": "u_demo", "days": 7}).json()
    assert some["total"] > 0
    assert client.get(f"/api/projects/{PID}/timeline", params={"actor": "nobody"}).json()["total"] == 0
    p1 = client.get(f"/api/projects/{PID}/timeline", params={"page_size": 5}).json()
    assert sum(len(d["entries"]) for d in p1["days"]) == 5 and p1["total"] > 5
    assert client.get("/api/projects/nope/timeline").status_code == 404
