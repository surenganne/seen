"""P4B-10 / quality gate: sentinel PII placed in a prompt, a file read and a diff never leaves as a value."""

import json
from pathlib import Path

import sqlalchemy as sa

from seen_core import audit, paths, sync
from seen_core.db import ledger_engine
from seen_core.pii import validators as v
from tests.helpers import Replay
from tests.pii.test_stop_scan import read_turn

AADHAAR = "98765432101" + v.verhoeff_digit("98765432101")
SPACED = f"{AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]}"
EMAIL = "sentinel.zz9@corp.test.in"
NEEDLES = [AADHAAR, SPACED, EMAIL, "sentinel.zz9"]


def everything_stored() -> str:
    with ledger_engine().connect() as c:
        tables = [r[0] for r in c.execute(sa.text("select name from sqlite_master where type='table'"))]
        rows = {t: [list(r) for r in c.execute(sa.text(f"select * from {t}"))] for t in tables}
    return json.dumps(rows, default=str) + json.dumps(audit.query(limit=100000))


def test_sentinel_never_leaves_as_a_value(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    paths.ensure_dir(seen_home)
    paths.config_toml().write_text('[pii]\nmode = "report"\n[sync]\nenabled = true\nsend_paths = true\nsend_pii_counts = true\nsend_audit = true\n')
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt(f"customer {EMAIL} has aadhaar {SPACED}")
    read_turn(rp, str(repo / "crm.csv"), f"1\t{EMAIL},{SPACED}")
    (repo / "a.py").write_text(f"one\ntwo\nX = '{EMAIL} {SPACED}'\n")
    rp.model_works()
    rp.stop(last_assistant_message=f"Updated record for {EMAIL}.")
    rp.fire("session-end", "session_end")

    payloads = json.dumps(sync.build_batch())
    stored = everything_stored()
    for n in NEEDLES:
        assert n not in payloads, f"{n} in sync payload"
        assert n not in stored, f"{n} stored in ledger/audit"
    with ledger_engine().connect() as c:
        kinds = {r[0] for r in c.execute(sa.text("select distinct source_kind from pii_findings"))}
        prompt = c.execute(sa.text("select prompt_text from changes")).scalar()
    assert {"prompt", "file_read", "diff_added"} <= kinds  # it was detected everywhere...
    assert "[EMAIL]" in prompt and "[AADHAAR]" in prompt    # ...and stored only redacted


def test_payload_respects_switches(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt(f"mail {EMAIL}")
    (repo / "a.py").write_text("one\ntwo\nthree\n")
    rp.model_works()
    rp.stop()
    paths.ensure_dir(seen_home)
    paths.config_toml().write_text("[sync]\nenabled = true\n")  # defaults: no paths, no PII counts, no audit
    ch = sync.build_batch()["changes"][0]
    assert "files" not in ch and ch["file_count"] == 1 and "pii" not in ch
    assert {"tok_in", "tok_out", "cost_usd", "skills"} <= set(ch)
    assert not ({"prompt_text", "summary", "prompt"} & set(ch))
    paths.config_toml().write_text("[sync]\nenabled = true\nsend_paths = true\nsend_pii_counts = true\nsend_tokens = false\n")
    ch = sync.build_batch()["changes"][0]
    assert ch["files"] == [{"path": "a.py", "added": 1, "removed": 0}] and ch["pii"]["state"] == "found"
    assert set(ch["pii"]) == {"state", "counts"} and "tok_in" not in ch


def test_disabled_sync_sends_nothing(seen_home: Path) -> None:
    assert sync.build_batch() == {"changes": [], "audit_heads": [], "audit": []}


def test_audit_sync_uses_per_type_detail_allowlist(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt("hello")
    rp.fire("post-tool", "post_tool_use_edit", tool_input={"file_path": str(repo / "a.py")})
    rp.model_works()
    rp.stop()
    audit.append([{"type": "custom.weird", "actor_kind": "system", "detail": {"anything": "x"}}])
    paths.ensure_dir(seen_home)
    paths.config_toml().write_text("[sync]\nenabled = true\nsend_audit = true\n")
    events = sync.build_batch()["audit"]
    blob = json.dumps(events)
    assert "prompt_hmac" not in blob and "content_hash" not in blob and '"hashes"' not in blob
    tool = next(e for e in events if e["type"] == "tool.call")
    assert set(tool["detail"]) <= {"tool", "cmd0", "skill"}
    assert next(e for e in events if e["type"] == "custom.weird")["detail"] == {}
    paths.config_toml().write_text("[sync]\nenabled = true\nsend_audit = true\nsend_paths = true\n")
    assert "path" in next(e for e in sync.build_batch()["audit"] if e["type"] == "tool.call")["detail"]
