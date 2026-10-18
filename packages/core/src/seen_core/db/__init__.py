"""Ledger database: engine, migrations, sessions."""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session, sessionmaker

from .. import paths

_ALEMBIC = Path(__file__).parent / "alembic"


def upgrade(url: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


def _sqlite_pragmas(dbapi_conn: object, _rec: object) -> None:
    cur = dbapi_conn.cursor()  # type: ignore[attr-defined]
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def make_engine(url: str) -> sa.Engine:
    os.umask(0o077)  # -wal/-shm siblings inherit 0600
    eng = sa.create_engine(url)
    if url.startswith("sqlite"):
        sa.event.listen(eng, "connect", _sqlite_pragmas)
    return eng


@cache
def _engine_for(url: str) -> sa.Engine:
    upgrade(url)
    return make_engine(url)


def ledger_url() -> str:
    db = paths.ledger_db()
    paths.ensure_dir(db.parent)
    if not db.exists():
        os.close(os.open(db, os.O_CREAT | os.O_WRONLY, 0o600))
    return f"sqlite:///{db}"


def ledger_engine() -> sa.Engine:
    return _engine_for(ledger_url())


def ledger_session() -> Session:
    return sessionmaker(ledger_engine(), expire_on_commit=False)()
