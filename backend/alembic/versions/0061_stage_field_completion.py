"""Customer Module Phase 1 — create stage_field_completion

Cache of required field completion state per project stage. Queried by the
pipeline advance_stage validation to block advancement when required fields
are missing. Updated whenever customer_field_values is written.

Revision ID: 0061
Revises: 0060
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0061'
down_revision = '0060'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'stage_field_completion',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stage_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('project_pipeline_stages.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('field_definition_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('field_definitions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('is_complete', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    # One completion state per (project, stage, field)
    op.create_unique_constraint(
        'uq_sfc_project_stage_field',
        'stage_field_completion',
        ['project_id', 'stage_id', 'field_definition_id'],
    )
    op.create_index(
        'ix_sfc_project_stage',
        'stage_field_completion',
        ['project_id', 'stage_id'],
    )
    op.create_index(
        'ix_sfc_tenant',
        'stage_field_completion',
        ['tenant_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_sfc_tenant', table_name='stage_field_completion')
    op.drop_index('ix_sfc_project_stage', table_name='stage_field_completion')
    op.drop_constraint('uq_sfc_project_stage_field', 'stage_field_completion', type_='unique')
    op.drop_table('stage_field_completion')
