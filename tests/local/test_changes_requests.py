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


def test_overview_counts_your_requests_and_shows_background_spend_apart(client: TestClient) -> None:
    from datetime import UTC, datetime

    from seen_core.db.models import PiiFinding

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with ledger_session() as db:
        db.add(Project(id="pov", name="r"))
        for sid, ep, cid, cost, model in (("o-mine", "cli", "oc-mine", 1.0, "claude-opus-5-5"),
                                          ("o-bg", "sdk-py", "oc-bg", 0.25, "claude-haiku-5-5")):
            db.add(Session(id=sid, project_id="pov", started_at=now, entrypoint=ep))
            db.add(Change(id=cid, project_id="pov", session_id=sid, seq=1, started_at=now, cost_usd=cost, model=model))
        db.add(PiiFinding(id="f-bg", change_id="oc-bg", type="card", confidence="high", count=1, distinct_count=1,
                          source_kind="file_read", status="open"))
        db.commit()
    o = client.get("/api/projects/pov/overview").json()
    t = o["tiles"]
    assert t["changes"] == 1 and t["cost_usd"] == 1.0
    assert t["background_changes"] == 1 and t["background_cost_usd"] == 0.25
    assert [m["model"] for m in o["by_model"]] == ["claude-opus-5-5"]
    # a plugin session that read personal data is still an exposure: PII and the alert count every session
    assert t["pii_high"] == 1 and o["alert"]["on"]


def test_injected_turns_read_as_what_they_are(client: TestClient) -> None:
    _add("s-inj", "cli", "c-cmd", "<command-name>/login</command-name>\n<command-message>login</command-message>\n<command-args></command-args>", "")
    with ledger_session() as db:
        db.add(Change(id="c-note", project_id="preq", session_id="s-inj", seq=2, started_at="2099-01-01T00:01:00Z",
                      prompt_text="<task-notification>\n<summary>Commit security review found 3 issues</summary></task-notification>"))
        db.commit()
    by = {c["id"]: c for c in client.get("/api/projects/preq/changes").json()["items"]}
    assert by["c-cmd"]["request"] == "/login"
    assert by["c-note"]["request"] == "Automatic follow-up: a background task finished (Commit security review found 3 issues)"
