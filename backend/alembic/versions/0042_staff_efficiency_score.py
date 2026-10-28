"""staff efficiency score

Revision ID: 0042
Revises: 0041
Create Date: 2026-05-13
"""

from alembic import op
import sqlalchemy as sa

revision = '0042'
down_revision = '0041'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'staff_profiles',
        sa.Column('efficiency_score', sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        'staff_profiles',
        sa.Column('efficiency_computed_at', sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('staff_profiles', 'efficiency_computed_at')
    op.drop_column('staff_profiles', 'efficiency_score')
