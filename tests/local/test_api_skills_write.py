import json
from pathlib import Path

from fastapi.testclient import TestClient

from seen_core import audit

PID = "demo-payments"
H = {"X-Seen-Request": "1"}


def lockfile(seeded: Path) -> dict:
    return json.loads((seeded / "demo-repos/payments-api/.seen/skills.lock.json").read_text())


def test_approve_updates_lockfile_ui_and_audit(client: TestClient, seeded: Path) -> None:
    before = next(s for s in client.get("/api/skills", params={"project": PID}).json() if s["id"] == "release-notes")
    assert before["status"] == "unreviewed"
    r = client.post("/api/skills/release-notes/approve", params={"project": PID}, headers=H)
    assert r.status_code == 200
    assert before["hash"][:7] in lockfile(seeded)["approved"]["release-notes"]
    after = client.get("/api/skills/release-notes", params={"project": PID}).json()
    assert after["status"] == "approved" and after["versions"][0]["approved"] and after["versions"][0]["approved_by"]
    ev = audit.query(type_="approval.skill")[0]
    assert ev["subject"] == "release-notes" and ev["detail"]["old"] == "unreviewed" and ev["detail"]["new"] == "approved"


def test_changed_skill_can_be_reapproved(client: TestClient) -> None:
    assert next(s for s in client.get("/api/skills", params={"project": PID}).json() if s["id"] == "tdd")["status"] == "changed"
    client.post("/api/skills/tdd/approve", params={"project": PID}, headers=H)
    assert next(s for s in client.get("/api/skills", params={"project": PID}).json() if s["id"] == "tdd")["status"] == "approved"


def test_block_and_approve_unblocks(client: TestClient, seeded: Path) -> None:
    assert client.post("/api/skills/security-review/block", params={"project": PID}, headers=H).status_code == 200
    assert "security-review" in lockfile(seeded)["blocked"]
    assert client.get("/api/skills/security-review", params={"project": PID}).json()["status"] == "blocked"
    assert audit.query(type_="approval.skill")[0]["detail"]["new"] == "blocked"
    client.post("/api/skills/security-review/approve", params={"project": PID}, headers=H)
    assert "security-review" not in lockfile(seeded)["blocked"]


def test_unknown_skill_or_project_404(client: TestClient) -> None:
    assert client.post("/api/skills/nope/approve", params={"project": PID}, headers=H).status_code == 404
    assert client.post("/api/skills/tdd/approve", params={"project": "nope"}, headers=H).status_code == 404
