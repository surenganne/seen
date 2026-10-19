"""sessions.entrypoint: how Claude Code was started (cli, sdk-cli, sdk-py, ...); sdk-* is a plugin's background session

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('sessions') as b:
        b.add_column(sa.Column('entrypoint', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('sessions') as b:
        b.drop_column('entrypoint')
