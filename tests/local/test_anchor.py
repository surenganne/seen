import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from seen_core import audit, paths


def test_unanchored_by_default(client: TestClient) -> None:
    v = client.get("/api/audit/verify").json()
    assert v["anchored"] is False and "Not anchored" in v["anchor_note"]


def test_anchored_note_and_rewrite_detected(client: TestClient, seeded: Path) -> None:
    head = audit.verify()
    (paths.home() / "anchors.json").write_text(json.dumps({"seq": head.head_seq, "hash": head.head, "at": "2026-10-19T01:00:00Z",
                                                           "server": "team.example"}))
    v = client.get("/api/audit/verify").json()
    assert v["anchored"] is True and "anchored on team.example through seq" in v["anchor_note"].lower()
    c = sqlite3.connect(seeded / "audit.db", isolation_level=None)
    c.execute("DROP TRIGGER audit_no_delete")
    c.execute("CREATE TABLE IF NOT EXISTS audit_prune_token(x INTEGER)")
    c.execute(f"DELETE FROM audit_events WHERE seq >= {head.head_seq}")  # rewrite the tail after anchoring
    audit.append([{"type": "tool.call", "actor_kind": "agent", "detail": {"tool": "Edit"}}])
    paths.audit_heads().write_text("")
    v2 = client.get("/api/audit/verify").json()
    assert v2["ok"] is False and v2["anchored"] is True and "rewritten" in (v2["reason"] or "")
