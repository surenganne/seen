"""The Overview dashboard: every figure on the page is a sum of the daily series, so the parts must add up to the whole."""

from fastapi.testclient import TestClient

PID = "demo-payments"


def get(client: TestClient, range_: int = 28) -> dict:  # type: ignore[type-arg]
    return client.get(f"/api/projects/{PID}/overview", params={"range": range_}).json()  # type: ignore[no-any-return]


def test_daily_series_adds_up_to_the_tiles(client: TestClient) -> None:
    o = get(client)
    t, days = o["tiles"], o["by_day"]
    assert len(days) == 28 and [d["date"] for d in days] == sorted(d["date"] for d in days)
    assert sum(d["requests"] for d in days) == t["changes"] > 0
    assert sum(d["changed"] for d in days) == t["changed"] <= t["changes"]
    assert sum(d["added"] for d in days) == t["lines_added"] and sum(d["removed"] for d in days) == t["lines_removed"]
    assert round(sum(d["cost_usd"] for d in days), 3) == round(t["cost_usd"], 3)
    assert sum(d["tok_out"] for d in days) == t["tok_out"]
    assert sum(d["commits"] for d in days) >= t["commits"] > 0  # a commit seen on two days counts on each
    for d in days:
        assert round(sum(d["cost_by_model"].values()), 4) == round(d["cost_usd"], 4)
        assert d["changed"] <= d["requests"]


def test_tiles_split_tokens_and_carry_the_previous_period(client: TestClient) -> None:
    o = get(client, 7)
    t, prev = o["tiles"], o["prev"]
    assert set(prev) == set(t)
    assert t["tokens"] == t["tok_in"] + t["tok_out"] + t["tok_cache_read"] + t["tok_cache_write"]
    wide = get(client, 28)["tiles"]["changes"]
    assert t["changes"] + prev["changes"] <= wide + 1  # the previous 7 days sit just before the current 7 (all inside 28)


def test_governance_figures(client: TestClient) -> None:
    o = get(client)
    t = o["tiles"]
    assert sum(p["checks"] for p in o["policies"]) == t["policy_checks"]
    assert all(p["met"] <= p["checks"] for p in o["policies"]) and t["policy_checks"] - t["policy_met"] >= t["policy_missed"]
    assert set(o["skill_status"]) <= {"approved", "unreviewed", "changed", "blocked"}
    assert sum(o["skill_status"].values()) >= sum(s["runs"] for s in o["top_skills"])


def test_work_shape_figures(client: TestClient) -> None:
    o = get(client)
    t = o["tiles"]
    g = o["git"]
    assert g["committed"] + g["uncommitted"] + g["reverted"] <= t["changed"]
    assert g["committed"] >= t["commits"]
    counts = [a["changes"] for a in o["areas"]]
    assert 0 < len(counts) <= 8 and counts == sorted(counts, reverse=True)
    cells = o["rhythm"]
    assert sum(c["changes"] for c in cells) == t["changes"]
    assert all(0 <= c["dow"] <= 6 and 0 <= c["hour"] <= 23 and c["changes"] > 0 for c in cells)
