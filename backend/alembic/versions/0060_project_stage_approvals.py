"""Customer Module Phase 1 — create project_stage_approvals

Tracks manager/team-lead approval per project pipeline stage before advancement
is permitted. One row per (project, stage) approval. The approver_id is the
user who granted approval; notes captures their rationale.

Revision ID: 0060
Revises: 0059
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0060'
down_revision = '0059'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'project_stage_approvals',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        # References project_pipeline_stages.id
        sa.Column('stage_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('project_pipeline_stages.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('approver_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    # One approval record per (project, stage)
    op.create_unique_constraint(
        'uq_psa_project_stage',
        'project_stage_approvals',
        ['project_id', 'stage_id'],
    )
    op.create_index(
        'ix_psa_project',
        'project_stage_approvals',
        ['project_id'],
    )
    op.create_index(
        'ix_psa_tenant',
        'project_stage_approvals',
        ['tenant_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_psa_tenant', table_name='project_stage_approvals')
    op.drop_index('ix_psa_project', table_name='project_stage_approvals')
    op.drop_constraint('uq_psa_project_stage', 'project_stage_approvals', type_='unique')
    op.drop_table('project_stage_approvals')
