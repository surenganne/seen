"""A change that writes a memory note says so, and the note links back to it (no front-matter source_change needed)."""

from pathlib import Path

from fastapi.testclient import TestClient

from seen_core.db import ledger_session
from seen_core.db.models import Change, ChangeFile, Project
from seen_core.memory import files as mf


def test_change_lists_memory_it_wrote_and_note_links_back(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    mf.new_memory(root / ".seen/memory", id="use-uv", type="convention", body="Use uv.", file_ref="pyproject.toml")
    with ledger_session() as db:
        db.add(Project(id="pmem", name="repo", root_path=str(root)))
        db.add(Change(id="ch-mem", project_id="pmem", session_id="s", seq=1, started_at="2099-01-01T00:00:00Z", ended_at="2099-01-01T00:01:00Z"))
        db.add(ChangeFile(change_id="ch-mem", path="pyproject.toml", added=2, removed=0))
        db.add(ChangeFile(change_id="ch-mem", path=".seen/memory/use-uv.md", added=7, removed=0))
        db.commit()
    r = client.get("/api/changes/ch-mem")
    assert r.status_code == 200, r.text[:300]
    assert r.json()["memory_saved"] == ["use-uv"]
    note = next(m for m in client.get("/api/projects/pmem/memory").json()["items"] if m["id"] == "use-uv")
    assert note["source_change"] == "ch-mem" and note["status"] != "stale"
