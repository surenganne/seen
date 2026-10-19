"""sessions.source: live (hooks) or imported (seen import from a transcript)

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('sessions') as b:
        b.add_column(sa.Column('source', sa.Text(), nullable=False, server_default='live'))


def downgrade() -> None:
    with op.batch_alter_table('sessions') as b:
        b.drop_column('source')
