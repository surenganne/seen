"""outbox.dead_at, outbox.last_status: a batch the server rejected for good is parked, not retried forever

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('outbox') as b:
        b.add_column(sa.Column('dead_at', sa.Text(), nullable=True))
        b.add_column(sa.Column('last_status', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('outbox') as b:
        b.drop_column('last_status')
        b.drop_column('dead_at')
