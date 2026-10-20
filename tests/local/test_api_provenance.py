"""Provenance routes: per-file blocks and the range report. No route may 500; no response carries line text."""

import dataclasses
import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seen_core import config
from seen_core.db import ledger_session
from seen_core.db.models import Project
from seen_core.provenance import report as rp
from seen_local import provenance_api

PID = "demo-payments"
DEMO = "src/payments/charge.py"  # the first file of demo-payments: devseed attributes some of its lines to seeded changes
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@example.com"}


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, env=ENV, check=True, capture_output=True)


@pytest.fixture
def root(client: TestClient) -> Path:
    return Path(next(p for p in client.get("/api/projects").json() if p["id"] == PID)["root_path"])


def commit(root: Path, msg: str = "more") -> None:
    git(root, "add", "-A")
    git(root, "commit", "-qm", msg)


def file_url(path: str | None = DEMO, rev: str | None = None) -> tuple[str, dict[str, str]]:
    p = {k: v for k, v in (("path", path), ("rev", rev)) if v is not None}
    return f"/api/projects/{PID}/provenance/file", p


def get_file(client: TestClient, path: str | None = DEMO, rev: str | None = None) -> object:
    url, params = file_url(path, rev)
    return client.get(url, params=params)


def test_blocks_cover_every_line_once_and_counts_sum(client: TestClient, root: Path) -> None:
    r = get_file(client)
    assert r.status_code == 200, r.text
    j = r.json()
    n = len((root / DEMO).read_text().splitlines())
    covered = [i for b in j["blocks"] for i in range(b["start"], b["end"] + 1)]
    assert covered == list(range(1, n + 1))
    assert sum(j["counts"].values()) == n and set(j["counts"]) == {"agent", "human", "not_observed", "neutral"}
    assert j["counts"]["agent"] > 0 and j["counts"]["human"] > 0
    assert (j["path"], j["rev"], j["truncated"], j["reason"]) == (DEMO, "HEAD", False, None)
    agent = next(b for b in j["blocks"] if b["who"] == "agent")
    assert agent["change_id"] and agent["headline"] and agent["started_at"] and agent["model"]
    assert set(agent) == {"start", "end", "who", "change_id", "headline", "started_at", "model", "skills", "pii_state"}


def test_response_never_carries_line_text(client: TestClient, root: Path) -> None:
    body = get_file(client).text
    for ln in (root / DEMO).read_text().splitlines()[:5]:
        assert ln.strip() not in body


@pytest.mark.parametrize("path", [None, "", "../x", "src/../../x", "/etc/passwd", "-x", "a\x00b", "."])
def test_unsafe_path_is_422(client: TestClient, path: str | None) -> None:
    r = get_file(client, path)
    assert r.status_code == 422, (path, r.status_code, r.text)


def test_symlink_out_of_the_repo_is_422(client: TestClient, root: Path, tmp_path: Path) -> None:
    (tmp_path / "outside.txt").write_text("secret = 1\n")
    (root / "link.py").symlink_to(tmp_path / "outside.txt")
    assert get_file(client, "link.py").status_code == 422


@pytest.mark.parametrize("rev", ["-x", "--output=x", "a b", "x\x00y", "", "a" * 201])
def test_unsafe_rev_is_422(client: TestClient, rev: str) -> None:
    assert get_file(client, DEMO, rev).status_code == 422


def test_unsafe_detail_never_echoes_input(client: TestClient) -> None:
    r = get_file(client, DEMO, "-\x1b[31mred")
    assert r.status_code == 422 and "\x1b" not in r.text and "red" not in r.text


def test_not_tracked_and_missing_project_are_404(client: TestClient, root: Path) -> None:
    (root / "new.py").write_text("untracked_value = compute(1)\n")
    r = get_file(client, "new.py")
    assert r.status_code == 404 and r.json()["detail"].startswith("not tracked")
    assert get_file(client, "no/such/file.py").status_code == 404
    assert get_file(client, DEMO, "nosuchbranch").status_code == 404
    assert client.get("/api/projects/nope/provenance/file", params={"path": DEMO}).status_code == 404
    assert client.get("/api/projects/nope/provenance/range", params={"base": "HEAD"}).status_code == 404


def test_deleted_file_is_404(client: TestClient, root: Path) -> None:
    git(root, "rm", "-q", DEMO)
    commit(root, "drop")
    assert get_file(client).status_code == 404
    assert get_file(client, DEMO, "HEAD~1").status_code == 200


def test_project_without_a_usable_repo_is_404(client: TestClient, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q", "-b", "main")  # a repo with no HEAD
    with ledger_session() as db:
        db.add_all([Project(id="p-noroot", name="n", root_path=None, created_at="2026-01-01T00:00:00Z"),
                    Project(id="p-gone", name="g", root_path=str(tmp_path / "gone"), created_at="2026-01-01T00:00:00Z"),
                    Project(id="p-nohead", name="h", root_path=str(empty), created_at="2026-01-01T00:00:00Z")])
        db.commit()
    for pid in ("p-noroot", "p-gone", "p-nohead"):
        for tail, params in (("file", {"path": "a.py"}), ("range", {"base": "HEAD~1"})):
            r = client.get(f"/api/projects/{pid}/provenance/{tail}", params=params)
            assert r.status_code == 404, (pid, tail, r.status_code, r.text)


def test_binary_and_huge_files_are_capped_not_failed(client: TestClient, root: Path) -> None:
    (root / "img.bin").write_bytes(b"\x89PNG\x00\x01" + b"x" * 5000)
    (root / "big.txt").write_text("a line of generated text\n" * (50_000_000 // 25))  # 50 MB
    commit(root, "blobs")
    b = get_file(client, "img.bin")
    assert b.status_code == 200 and b.json()["reason"] == "binary" and b.json()["blocks"] == []
    big = get_file(client, "big.txt")
    assert big.status_code == 200 and big.json()["reason"] == "over 1 MB" and big.json()["blocks"] == []


def test_path_with_spaces_and_unicode(client: TestClient, root: Path) -> None:
    rel = "dir a/файл é.py"
    (root / "dir a").mkdir()
    (root / rel).write_text("".join(f"value_{i} = compute_something({i})\n" for i in range(6)))
    commit(root, "odd name")
    j = get_file(client, rel).json()
    assert j["path"] == rel and sum(j["counts"].values()) == 6
    assert [(b["start"], b["end"]) for b in j["blocks"]] == [(1, 6)]


def test_budget_timeout_is_truncated_not_500(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provenance_api, "BUDGET_S", 0)
    monkeypatch.setattr(provenance_api.blame.gitutil, "run", lambda *a, **k: None)
    r = get_file(client)
    assert r.status_code == 200 and r.json()["truncated"] is True and r.json()["blocks"] == []


def test_range_route_equals_build_report(client: TestClient, root: Path) -> None:
    (root / DEMO).write_text((root / DEMO).read_text() + "".join(f"extra_{i} = compute_total({i})\n" for i in range(4)))
    commit(root, "extend")
    r = client.get(f"/api/projects/{PID}/provenance/range", params={"base": "HEAD~1", "head": "HEAD"})
    assert r.status_code == 200, r.text
    with ledger_session() as db:
        want = dataclasses.asdict(rp.build_report(db, db.get(Project, PID), "HEAD~1", "HEAD"))
    assert r.json() == json.loads(json.dumps(want))
    assert r.json()["added"]["human"] >= 4 and "pii_unchecked" in r.json()


def test_range_errors(client: TestClient) -> None:
    url = f"/api/projects/{PID}/provenance/range"
    assert client.get(url, params={"base": "-x"}).status_code == 422
    assert client.get(url, params={"base": "HEAD", "head": "a b"}).status_code == 422
    assert client.get(url).status_code == 422
    r = client.get(url, params={"base": "nosuchref"})
    assert r.status_code == 404 and "nosuchref" in r.json()["detail"]


def test_settings_expose_provenance_read_only(client: TestClient) -> None:
    from seen_local import writes

    assert client.get("/api/settings").json()["provenance"] == config.load()["provenance"]
    assert "provenance" not in writes.EDITABLE
    before = config.load()["provenance"]
    client.put("/api/settings", json={"provenance": {"enabled": not before["enabled"]}}, headers={"X-Seen-Request": "1"})
    assert config.load()["provenance"] == before
