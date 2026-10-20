"""project memory removed: drop change_memories and changes.mem_state / mem_injected_tokens

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table('change_memories')
    with op.batch_alter_table('changes') as b:
        b.drop_column('mem_state')
        b.drop_column('mem_injected_tokens')


def downgrade() -> None:  # the data is gone: the columns come back empty
    with op.batch_alter_table('changes') as b:
        b.add_column(sa.Column('mem_injected_tokens', sa.Integer(), nullable=False, server_default='0'))
        b.add_column(sa.Column('mem_state', sa.Text(), nullable=True))
    op.create_table('change_memories',
        sa.Column('change_id', sa.String(), nullable=False),
        sa.Column('memory_id', sa.String(), nullable=False),
        sa.Column('content_hash', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('change_id', 'memory_id'))
