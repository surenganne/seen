"""line_prints: keyed line fingerprints for provenance (never line text)

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('line_prints',
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('path', sa.String(), nullable=False),
        sa.Column('fp', sa.LargeBinary(), nullable=False),
        sa.Column('change_id', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('project_id', 'path', 'fp', 'change_id'))
    op.create_index('ix_line_prints_change', 'line_prints', ['change_id'])


def downgrade() -> None:
    op.drop_index('ix_line_prints_change', table_name='line_prints')
    op.drop_table('line_prints')
