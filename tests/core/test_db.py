from pathlib import Path

import sqlalchemy as sa

from seen_core.db import ledger_engine, upgrade

TABLES = {"projects", "sessions", "changes", "change_files", "change_memories", "skills", "skill_versions",
          "skill_invocations", "policies", "policy_results", "pii_findings", "outbox"}


def test_upgrade_head_creates_all_tables(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'l.db'}"
    upgrade(url)
    insp = sa.inspect(sa.create_engine(url))
    assert set(insp.get_table_names()) >= TABLES
    cols = {c["name"] for c in insp.get_columns("changes")}
    assert {"tok_cache_write", "price_version", "pii_state", "mem_state", "git_status", "synced_at"} <= cols


def test_ledger_engine_uses_wal_and_migrates(seen_home: Path) -> None:
    eng = ledger_engine()
    with eng.connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert "changes" in sa.inspect(c).get_table_names()
    assert (seen_home / "ledger.db").exists()


def test_ledger_file_is_0600(seen_home: Path) -> None:
    ledger_engine()
    assert ((seen_home / "ledger.db").stat().st_mode & 0o777) == 0o600


def test_concurrent_first_use_is_safe(seen_home: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from seen_core import db as dbmod

    dbmod._engine_for.cache_clear()
    with ThreadPoolExecutor(8) as ex:
        engines = list(ex.map(lambda _: dbmod.ledger_engine(), range(16)))
    assert len({id(e) for e in engines}) == 1
