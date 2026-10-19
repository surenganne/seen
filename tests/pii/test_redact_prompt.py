import json
from pathlib import Path

import pytest
import sqlalchemy as sa

from seen_core import audit, paths, spool
from seen_core.db import ledger_engine
from seen_core.pii import validators as v
from seen_core.pii.projectcfg import load_project
from seen_core.redact import redact
from tests.helpers import Replay

AADHAAR = "23456789012" + v.verhoeff_digit("23456789012")
SENTINEL = f"my aadhaar is {AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]} and mail sentinel.person@corp.test.in"


def test_redact_replaces_spans_with_type_markers() -> None:
    out = redact(SENTINEL)
    assert "[AADHAAR]" in out and "[EMAIL]" in out and AADHAAR[:4] not in out and "sentinel.person" not in out


def test_redact_home_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/dev")
    assert redact("open /Users/dev/repos/x.py") == "open ~/repos/x.py"


def test_pii_yaml_subset_parser(tmp_path: Path) -> None:
    (tmp_path / ".seen").mkdir()
    (tmp_path / ".seen/pii.yaml").write_text(
        '# comment\nallow_paths: ["tests/fixtures/**", docs/sample-data/**]\nallow_values:\n  - "*@example.com"\n  - "*@test.local"\n'
        'custom_rules:\n  - id: mrn\n    type: custom\n    pattern: "\\\\bMRN[:# ]*\\\\d{6,10}\\\\b"\n    confidence: medium\n')
    c = load_project(tmp_path)
    assert c["allow_paths"] == ["tests/fixtures/**", "docs/sample-data/**"]
    assert c["allow_values"] == ["*@example.com", "*@test.local"]
    assert c["custom_rules"][0] == {"id": "mrn", "type": "custom", "pattern": "\\bMRN[:# ]*\\d{6,10}\\b", "confidence": "medium"}


def _mode(seen_home: Path, mode: str, store: str = "redacted") -> None:
    paths.ensure_dir(seen_home)
    paths.config_toml().write_text(f'[pii]\nmode = "{mode}"\nstore_prompt_text = "{store}"\n')


def test_report_mode_records_and_stores_redacted(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    _mode(seen_home, "report")
    r = Replay(repo, tmp_path)
    r.start()
    res = r.prompt(SENTINEL)
    assert res.code == 0 and "systemMessage" not in res.stdout
    r.model_works()
    r.stop()
    with ledger_engine().connect() as c:
        prompt = c.execute(sa.text("select prompt_text, pii_state, pii_count from changes")).one()
        f = c.execute(sa.text("select type, source_kind, destination, fingerprints_json from pii_findings where source_kind='prompt'")).all()
    assert "[AADHAAR]" in prompt[0] and AADHAAR[:4] not in prompt[0]
    assert prompt[1] == "found" and prompt[2] >= 2
    assert {x[0] for x in f} >= {"aadhaar", "email"} and all(x[2] == "model" for x in f)
    blob = json.dumps([list(x) for x in f]) + json.dumps(audit.query(limit=10000)) + (paths.spool_file("sess-1").read_text())
    assert AADHAAR not in blob.replace(" ", "") and "sentinel.person" not in blob


def test_warn_mode_shows_user_message(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    _mode(seen_home, "warn")
    r = Replay(repo, tmp_path)
    r.start()
    res = r.prompt(SENTINEL)
    msg = json.loads(res.stdout)["systemMessage"]
    assert res.code == 0 and "aadhaar" in msg.lower() and AADHAAR[:4] not in msg


def test_block_mode_stops_prompt(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    _mode(seen_home, "block")
    r = Replay(repo, tmp_path)
    r.start()
    res = r.prompt(SENTINEL)
    assert res.code == 2 and "aadhaar" in res.stderr.lower() and AADHAAR[:4] not in res.stderr
    assert [x for x in spool.read("sess-1") if x["ev"] == "pii_prompt"][0]["blocked"] is True


def test_off_mode_and_store_off(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    _mode(seen_home, "off", store="off")
    r = Replay(repo, tmp_path)
    r.start()
    assert r.prompt(SENTINEL).code == 0
    r.model_works()
    r.stop()
    with ledger_engine().connect() as c:
        assert c.execute(sa.text("select prompt_text from changes")).scalar() is None
        assert c.execute(sa.text("select count(*) from pii_findings where source_kind='prompt'")).scalar() == 0


def test_project_allow_values_respected(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    _mode(seen_home, "block")
    (repo / ".seen").mkdir()
    (repo / ".seen/pii.yaml").write_text('allow_values: ["*@corp.test.in"]\n')
    r = Replay(repo, tmp_path)
    r.start()
    assert r.prompt("mail sentinel.person@corp.test.in please").code == 0


def test_summary_is_redacted(repo: Path, tmp_path: Path) -> None:
    r = Replay(repo, tmp_path)
    r.start()
    r.prompt()
    r.model_works()
    r.stop(last_assistant_message="Emailed sentinel.person@corp.test.in. Done.")
    with ledger_engine().connect() as c:
        s = c.execute(sa.text("select summary from changes")).scalar()
    assert "sentinel.person" not in s and "[EMAIL]" in s


def test_block_mode_still_applies_outside_git_repo(tmp_path: Path, seen_home: Path) -> None:
    _mode(seen_home, "block")
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    r = Replay(plain, tmp_path)
    r.start()
    res = r.prompt(SENTINEL)
    assert res.code == 2 and AADHAAR[:4] not in res.stderr
    assert spool.read("sess-1") == []  # not recorded: no repo
