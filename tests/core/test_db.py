from pathlib import Path

import sqlalchemy as sa

from seen_core.db import ledger_engine, upgrade

TABLES = {"projects", "sessions", "changes", "change_files", "skills", "skill_versions",
          "skill_invocations", "policies", "policy_results", "pii_findings", "outbox"}


def test_upgrade_head_creates_all_tables(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'l.db'}"
    upgrade(url)
    insp = sa.inspect(sa.create_engine(url))
    assert set(insp.get_table_names()) >= TABLES
    cols = {c["name"] for c in insp.get_columns("changes")}
    assert "change_memories" not in insp.get_table_names() and not {"mem_state", "mem_injected_tokens"} & cols
    assert {"tok_cache_write", "price_version", "pii_state", "git_status", "synced_at"} <= cols


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


def test_migration_0005_drops_memory_and_keeps_changes(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'l.db'}"
    upgrade(url, "0004")
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.execute(sa.text("INSERT INTO changes (id, tok_in, tok_out, tok_cache_read, tok_cache_write, mem_state, mem_injected_tokens, pii_count) "
                          "VALUES ('c1', 1, 2, 3, 4, 'loaded', 900, 0)"))
        c.execute(sa.text("INSERT INTO change_memories (change_id, memory_id) VALUES ('c1', 'm1')"))
    upgrade(url)
    insp = sa.inspect(eng)
    assert "change_memories" not in insp.get_table_names()
    assert not {"mem_state", "mem_injected_tokens"} & {c["name"] for c in insp.get_columns("changes")}
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT tok_out FROM changes WHERE id = 'c1'")).scalar() == 2


def test_migration_0006_adds_line_prints_and_keeps_data(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'l.db'}"
    upgrade(url, "0005")
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.execute(sa.text("INSERT INTO changes (id, tok_in, tok_out, tok_cache_read, tok_cache_write, pii_count) VALUES ('c1', 1, 2, 3, 4, 0)"))
    upgrade(url)
    assert "line_prints" in sa.inspect(eng).get_table_names()
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT tok_out FROM changes WHERE id = 'c1'")).scalar() == 2
    from alembic import command
    from alembic.config import Config

    from seen_core import db as dbmod

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(dbmod.__file__).parent / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.downgrade(cfg, "0005")
    assert "line_prints" not in sa.inspect(eng).get_table_names()
