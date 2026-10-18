import csv
import json
from pathlib import Path

from seen_core import audit, export
from tests.core.test_audit import ev


def test_ndjson_export_with_manifest(seen_home: Path, tmp_path: Path) -> None:
    audit.append([ev(i, occurred_at=f"2026-10-{10 + i:02d}T00:00:00Z") for i in range(1, 6)])
    out = export.export(tmp_path / "x", project="p1", date_from="2026-10-12", date_to="2026-10-14", fmt="ndjson", actor="u_1")
    lines = [json.loads(x) for x in out.read_text().splitlines()]
    assert [e["subject"] for e in lines] == ["Edit:2", "Edit:3", "Edit:4"]
    m = json.loads(out.with_suffix(".manifest.json").read_text())
    assert m["count"] == 3 and m["verification"]["ok"] and m["format"] == "ndjson" and m["schema_version"]
    assert m["head_hash"] == audit.verify().head or m["head_hash"]
    assert audit.query(type_="export.created")[0]["detail"]["count"] == 3


def test_csv_export(seen_home: Path, tmp_path: Path) -> None:
    audit.append([ev(1)])
    out = export.export(tmp_path / "y", project=None, date_from=None, date_to=None, fmt="csv", actor="u_1")
    rows = list(csv.DictReader(out.open()))
    assert rows[0]["type"] == "tool.call" and "hash" in rows[0] and json.loads(rows[0]["detail"])["tool"] == "Edit"


def test_export_refuses_broken_chain_marker(seen_home: Path, tmp_path: Path) -> None:
    import sqlite3

    audit.append([ev(i) for i in range(3)])
    c = sqlite3.connect(seen_home / "audit.db", isolation_level=None)
    c.execute("DROP TRIGGER audit_no_update")
    c.execute("UPDATE audit_events SET outcome='x' WHERE seq=2")
    out = export.export(tmp_path / "z", project=None, date_from=None, date_to=None, fmt="ndjson", actor="u_1")
    assert json.loads(out.with_suffix(".manifest.json").read_text())["verification"]["ok"] is False
