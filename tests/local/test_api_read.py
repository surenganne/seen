from fastapi.testclient import TestClient

PID = "demo-payments"


def test_projects(client: TestClient) -> None:
    r = client.get("/api/projects").json()
    assert {p["id"] for p in r} == {"demo-payments", "demo-patient", "demo-pipes"}
    p = next(x for x in r if x["id"] == PID)
    assert p["name"] == "payments-api" and p["changes"] > 0 and p["root_path"].startswith(("~", "/"))


def test_project_alert_carries_its_reasons(client: TestClient) -> None:
    for p in client.get("/api/projects").json():
        # the card says why, so a flag is never a bare alarm; no flag means no reasons
        assert bool(p["alert_reasons"]) == p["alert"]
        assert all(isinstance(x, str) and x for x in p["alert_reasons"])


def test_overview_ranges(client: TestClient) -> None:
    o7 = client.get(f"/api/projects/{PID}/overview?range=7").json()
    o28 = client.get(f"/api/projects/{PID}/overview?range=28").json()
    assert o28["tiles"]["changes"] >= o7["tiles"]["changes"] > 0
    assert len(o7["by_day"]) == 7 and o7["by_model"] and o7["areas"]
    assert {"cost_usd", "tokens", "policy_missed", "pii_changes", "files_changed"} <= set(o7["tiles"])
    assert client.get(f"/api/projects/{PID}/overview?range=9").status_code == 422


def test_changes_filters_and_sort(client: TestClient) -> None:
    all_ = client.get(f"/api/projects/{PID}/changes", params={"page_size": 200}).json()
    assert all_["total"] == len(all_["items"]) > 10
    f = all_["items"][0]["files"][0]
    by_file = client.get(f"/api/projects/{PID}/changes", params={"file": f}).json()["items"]
    assert by_file and all(f in c["files"] for c in by_file)
    missed = client.get(f"/api/projects/{PID}/changes", params={"policy_missed": True}).json()["items"]
    assert all(c["policy_missed"] for c in missed)
    sk = client.get(f"/api/projects/{PID}/changes", params={"skill": "security-review"}).json()["items"]
    assert sk and all("security-review" in c["skills"] for c in sk)
    pii = client.get(f"/api/projects/{PID}/changes", params={"pii": True}).json()["items"]
    assert pii and all(c["pii_count"] > 0 for c in pii)
    cost = client.get(f"/api/projects/{PID}/changes", params={"sort": "cost", "dir": "asc"}).json()["items"]
    assert [c["cost_usd"] for c in cost] == sorted(c["cost_usd"] for c in cost)
    q = client.get(f"/api/projects/{PID}/changes", params={"q": "refund"}).json()["items"]
    assert q and all("refund" in ((c["summary"] or "") + (c["request"] or "") + " ".join(c["files"])).lower() for c in q)
    st = client.get(f"/api/projects/{PID}/changes", params={"status": "committed"}).json()["items"]
    assert all(c["git_status"] == "committed" for c in st)


def test_change_detail(client: TestClient) -> None:
    cid = client.get(f"/api/projects/{PID}/changes", params={"skill": "security-review"}).json()["items"][0]["id"]
    d = client.get(f"/api/changes/{cid}").json()
    assert d["id"] == cid and d["files"] and d["tokens"]["out"] > 0
    shares = [p["share"] for p in d["cost_breakdown"]]
    assert abs(sum(shares) - 1) < 0.01
    assert any(s["skill_id"] == "security-review" and s["hash_short"] for s in d["skills"])
    assert "policies" in d and "pii" in d and "memories" not in d
    assert client.get("/api/changes/nope").status_code == 404


def test_skills_inventory_and_detail(client: TestClient) -> None:
    s = client.get("/api/skills", params={"project": PID}).json()
    by = {x["id"]: x for x in s}
    assert by["quick-sql-helper"]["status"] == "blocked"
    assert by["tdd"]["status"] == "changed"
    assert by["security-review"]["status"] == "approved"
    assert by["release-notes"]["status"] == "unreviewed"
    assert all(x["kind"] == "plugin" for x in client.get("/api/skills", params={"project": PID, "kind": "plugin"}).json())
    d = client.get("/api/skills/security-review", params={"project": PID}).json()
    assert d["versions"] and d["recent_changes"] and d["runs"] > 0


def test_policies_compliance(client: TestClient) -> None:
    pols = client.get(f"/api/projects/{PID}/policies").json()
    assert {p["id"] for p in pols} == {f"{PID}:pol-auth", f"{PID}:pol-phi"}
    for p in pols:
        assert 0 <= p["compliance"] <= 1 and p["met"] + p["missed"] == p["applicable"]


def test_audit_list_filters_and_verify(client: TestClient) -> None:
    page = client.get(f"/api/projects/{PID}/audit").json()
    assert page["items"] and all(e["project_id"] == PID for e in page["items"])
    only = client.get(f"/api/projects/{PID}/audit", params={"type": "skill.invoked"}).json()["items"]
    assert only and all(e["type"] == "skill.invoked" for e in only)
    p2 = client.get(f"/api/projects/{PID}/audit", params={"page": 2}).json()
    assert p2["page"] == 2 and p2["items"][0]["seq"] != page["items"][0]["seq"]
    v = client.get("/api/audit/verify").json()
    assert v["ok"] and v["count"] > 1000 and v["anchored"] is False


def test_settings_read(client: TestClient) -> None:
    s = client.get("/api/settings").json()
    assert s["pii"]["mode"] == "report" and s["audit"]["retention_days"] == 365
    assert s["prices"]["verified"] is False and s["local_data"]["ledger"].endswith("ledger.db")


def test_openapi_schema(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/api/projects/{pid}/overview" in spec["paths"]


def test_skills_most_recently_used_first(client: TestClient) -> None:
    items = client.get("/api/skills", params={"project": PID}).json()
    used = [s["last_used"] for s in items if s["last_used"]]
    assert used and used == sorted(used, reverse=True)
    first_unused = next(i for i, s in enumerate(items) if not s["last_used"])
    assert all(not s["last_used"] for s in items[first_unused:])  # never-used skills come after every used one
