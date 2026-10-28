"""
OPSYN PIPELINE TEMPLATE STAGES MIGRATION
Revision: 0022

Adds pipeline_template_stages table for defining stages within pipeline templates.

pipeline_template_stages table:
  + id                      UUID PRIMARY KEY DEFAULT gen_random_uuid()
  + template_id             UUID FK pipeline_templates.id NOT NULL
  + stage_order             INTEGER NOT NULL
  + stage_name              VARCHAR(200) NOT NULL
  + department_id           UUID FK departments.id NOT NULL
  + is_required             BOOLEAN DEFAULT TRUE
  + is_parallel             BOOLEAN DEFAULT FALSE
  + parallel_gate_stage_order INTEGER NULLABLE
  + expected_duration_days  INTEGER NULLABLE
  + created_at              TIMESTAMPTZ DEFAULT now()

UNIQUE(template_id, stage_order)

Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0022'
down_revision = '0021'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table('pipeline_template_stages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('template_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('stage_order', sa.Integer(), nullable=False),
        sa.Column('stage_name', sa.String(200), nullable=False),
        sa.Column('department_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('is_parallel', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('parallel_gate_stage_order', sa.Integer(), nullable=True),
        sa.Column('expected_duration_days', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    op.create_foreign_key(
        'fk_pipeline_template_stages_template_id',
        'pipeline_template_stages', 'pipeline_templates',
        ['template_id'], ['id'],
        ondelete='CASCADE'
    )

    op.create_foreign_key(
        'fk_pipeline_template_stages_department_id',
        'pipeline_template_stages', 'departments',
        ['department_id'], ['id'],
        ondelete='CASCADE'
    )

    op.create_unique_constraint(
        'uq_pipeline_template_stages_template_id_stage_order',
        'pipeline_template_stages',
        ['template_id', 'stage_order']
    )


def downgrade() -> None:
    op.drop_table('pipeline_template_stages')