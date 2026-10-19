"""Changes are the person's requests: each row leads with what was asked, and plugin background sessions are
kept out of the default view (ADR 0010)."""

from fastapi.testclient import TestClient

from seen_core.db import ledger_session
from seen_core.db.models import Change, Project, Session


def _add(sid: str, ep: str | None, cid: str, prompt: str | None, summary: str) -> None:
    with ledger_session() as db:
        if db.get(Project, "preq") is None:
            db.add(Project(id="preq", name="r"))
        db.add(Session(id=sid, project_id="preq", started_at="2099-01-01T00:00:00Z", entrypoint=ep))
        db.add(Change(id=cid, project_id="preq", session_id=sid, seq=1, started_at="2099-01-01T00:00:00Z",
                      prompt_text=prompt, summary=summary))
        db.commit()


def test_rows_lead_with_the_request_and_background_is_separate(client: TestClient) -> None:
    _add("s-mine", "cli", "c-mine", "Fix the  login\nbug in [EMAIL]'s account", "Fixed it.")
    _add("s-bg", "sdk-py", "c-bg", "# Episode window (redacted)", "Staged 2 intents.")
    every = client.get("/api/projects/preq/changes").json()
    by = {c["id"]: c for c in every["items"]}
    assert by["c-mine"]["request"] == "Fix the login bug in [EMAIL]'s account" and by["c-mine"]["summary"] == "Fixed it."
    assert by["c-bg"]["background"] and not by["c-mine"]["background"]
    yours = client.get("/api/projects/preq/changes", params={"kind": "yours"}).json()
    assert [c["id"] for c in yours["items"]] == ["c-mine"]
    assert yours["counts"] == {"all": 2, "yours": 1, "background": 1}
    assert [c["id"] for c in client.get("/api/projects/preq/changes", params={"q": "login"}).json()["items"]] == ["c-mine"]
