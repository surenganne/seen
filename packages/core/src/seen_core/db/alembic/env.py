from alembic import context
from sqlalchemy import engine_from_config, pool

from seen_core.db.models import Base

cfg = context.config
with engine_from_config(cfg.get_section(cfg.config_ini_section) or {}, prefix="sqlalchemy.", poolclass=pool.NullPool).connect() as conn:
    context.configure(connection=conn, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
