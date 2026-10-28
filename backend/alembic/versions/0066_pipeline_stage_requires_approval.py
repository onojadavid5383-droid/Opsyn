"""Phase 4 — add requires_approval flag to pipeline_template_stages

Enables per-stage approval gates. When True, advance_stage() blocks
advancement until a project_stage_approvals record with approved_at
exists for the current stage.

Revision ID: 0066
Revises: 0065
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa

revision = '0066'
down_revision = '0065'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'pipeline_template_stages',
        sa.Column('requires_approval', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('pipeline_template_stages', 'requires_approval')
