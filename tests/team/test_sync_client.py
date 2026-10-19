from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from seen_core import audit, identity, paths, sync
from seen_core.db import ledger_engine
from tests.helpers import Replay
from tests.team.conftest import make_key


def transport_for(team: TestClient, fail_first: int = 0) -> Any:
    calls = {"n": 0}

    def send(url: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, Any]]:
        calls["n"] += 1
        if calls["n"] <= fail_first:
            return 503, {"detail": "down"}
        r = team.post("/" + url.split("/", 3)[3], content=body, headers=headers)
        return r.status_code, r.json()

    send.calls = calls  # type: ignore[attr-defined]
    return send


@pytest.fixture
def recorded(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    from tests.conftest import git

    git(repo, "remote", "add", "origin", "https://github.com/acme/demo.git")
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    (repo / "a.py").write_text("one\ntwo\nthree\n")
    rp.model_works()
    rp.stop()
    rp.fire("session-end", "session_end")
    paths.ensure_dir(seen_home)
    paths.config_toml().write_text('[sync]\nenabled = true\nserver = "http://localhost:47824"\n')


def pid() -> str:
    with ledger_engine().connect() as c:
        return str(c.execute(sa.text("select id from projects")).scalar())


def test_push_marks_synced_and_anchors(recorded: None, team: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEEN_TEAM_API_KEY", make_key(team, pid(), "member", user=identity.user_id()))
    r = sync.push(transport=transport_for(team))
    assert r["sent"] == 1 and r["failed"] == 0
    with ledger_engine().connect() as c:
        assert c.execute(sa.text("select synced_at from changes")).scalar()
        assert c.execute(sa.text("select sent_at from outbox")).scalar()
    a = sync.anchor()
    assert a and a["seq"] > 0 and len(a["hash"]) == 64
    ev = audit.query(type_="sync.batch")[0]
    assert ev["detail"]["count"] == 1 and ev["detail"]["server"] == "localhost:47824"
    assert sync.push(transport=transport_for(team))["sent"] == 0  # nothing new


def test_retry_keeps_outbox_until_ack(recorded: None, team: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEEN_TEAM_API_KEY", make_key(team, pid(), "member", user=identity.user_id()))
    t = transport_for(team, fail_first=1)
    first = sync.push(transport=t, now_offset_s=0)
    assert first["failed"] == 1 and first["sent"] == 0
    with ledger_engine().connect() as c:
        assert c.execute(sa.text("select attempts from outbox")).scalar() == 1
        assert c.execute(sa.text("select synced_at from changes")).scalar() is None
    assert sync.push(transport=t, now_offset_s=0)["sent"] == 0  # backoff: not yet due
    assert sync.push(transport=t, now_offset_s=3600)["sent"] == 1


def test_resend_is_idempotent_on_server(recorded: None, team: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEEN_TEAM_API_KEY", make_key(team, pid(), "member", user=identity.user_id()))
    batch = sync.enqueue()
    assert batch is not None
    t = transport_for(team)
    for _ in range(2):
        with ledger_engine().begin() as c:
            c.execute(sa.text("update outbox set sent_at = null"))
        sync.push(transport=t, now_offset_s=0)
    lead = make_key(team, pid(), "lead")
    assert team.get("/api/projects", headers={"Authorization": f"Bearer {lead}"}).json()[0]["changes"] == 1


def test_no_key_or_plain_http_refused(recorded: None, seen_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEEN_TEAM_API_KEY", raising=False)
    with pytest.raises(sync.SyncError, match="SEEN_TEAM_API_KEY"):
        sync.push(transport=lambda *a: (200, {}))
    monkeypatch.setenv("SEEN_TEAM_API_KEY", "k")
    paths.config_toml().write_text('[sync]\nenabled = true\nserver = "http://team.example.com"\n')
    with pytest.raises(sync.SyncError, match="https"):
        sync.push(transport=lambda *a: (200, {}))


def test_install_id_is_random_not_identity(seen_home: Path) -> None:
    a = sync.install_id()
    assert a == sync.install_id() and len(a) >= 20 and "@" not in a
