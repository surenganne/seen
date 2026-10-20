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


def test_timeline_shows_only_file_changes_unless_asked(client: TestClient) -> None:
    t = client.get(f"/api/projects/{PID}/timeline", params={"page_size": 200}).json()
    flat = [e for d in t["days"] for e in d["entries"]]
    assert flat and all(e["files"] for e in flat)
    assert t["quiet_hidden"] >= 0
    every = client.get(f"/api/projects/{PID}/timeline", params={"page_size": 200, "all_turns": True}).json()
    assert every["total"] == t["total"] + t["quiet_hidden"] and every["quiet_hidden"] == 0


def test_timeline_entries_have_a_one_line_headline_and_areas(client: TestClient) -> None:
    t = client.get(f"/api/projects/{PID}/timeline", params={"page_size": 200}).json()
    for e in (e for d in t["days"] for e in d["entries"]):
        assert e["headline"] and "\n" not in e["headline"] and len(e["headline"]) <= 141
        assert 1 <= len(e["areas"]) <= 3 and all("/" not in a.strip("/") or a.count("/") == 1 for a in e["areas"])


def test_timeline_day_stats_add_up(client: TestClient) -> None:
    t = client.get(f"/api/projects/{PID}/timeline", params={"page_size": 200}).json()
    for d in t["days"]:
        assert d["changes"] == len(d["entries"])
        assert d["added"] == sum(e["added"] for e in d["entries"]) and d["removed"] == sum(e["removed"] for e in d["entries"])
        assert d["commits"] == len({e["commit"] for e in d["entries"] if e["git_status"] == "committed" and e["commit"]})
        assert d["files"] == len({f for e in d["entries"] for f in e["files"]})


def test_headline_rules() -> None:
    from seen_core.headline import areas_of, headline_of

    assert headline_of("**Fixed** the `refund` retry. Then more detail.", None, ["a.py"]) == "Fixed the refund retry."
    assert headline_of(None, "add a divide function\nplease", ["calc.py"]) == "add a divide function please"
    long = headline_of("x" * 300, None, ["a.py"])
    assert len(long) == 140 and long.endswith("…")
    assert headline_of("Ok.", None, ["web/src/a.tsx", "web/src/b.tsx"]) == "Changed 2 files in web/src"
    assert headline_of(None, None, ["a.py"]) == "Changed 1 file in (root)"
    assert areas_of(["packages/core/src/x.py", "packages/core/src/y.py", "web/src/p/A.tsx", "README.md", "docs/a.md", "docs/b.md"]) == [
        "packages/core", "docs", "web/src"]
