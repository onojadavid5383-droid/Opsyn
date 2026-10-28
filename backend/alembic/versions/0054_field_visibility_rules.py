"""Customer Module Phase 1 — create field_visibility_rules

Fine-grained stage × department visibility matrix for customer form fields.
Controls which fields are visible/required at each pipeline stage per department.

Revision ID: 0054
Revises: 0053
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0054'
down_revision = '0053'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'field_visibility_rules',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('field_definition_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('field_definitions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stage_order', sa.Integer(), nullable=False),
        sa.Column('department_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('departments.id', ondelete='CASCADE'), nullable=False),
        # True means this field must be complete before stage can advance
        sa.Column('is_required_to_advance', sa.Boolean(), nullable=False,
                  server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    # One rule per (field × stage × department)
    op.create_unique_constraint(
        'uq_fvr_field_stage_dept',
        'field_visibility_rules',
        ['field_definition_id', 'stage_order', 'department_id'],
    )
    op.create_index(
        'ix_fvr_field_definition',
        'field_visibility_rules',
        ['field_definition_id'],
    )
    op.create_index(
        'ix_fvr_tenant_stage',
        'field_visibility_rules',
        ['tenant_id', 'stage_order'],
    )


def downgrade() -> None:
    op.drop_index('ix_fvr_tenant_stage', table_name='field_visibility_rules')
    op.drop_index('ix_fvr_field_definition', table_name='field_visibility_rules')
    op.drop_constraint('uq_fvr_field_stage_dept', 'field_visibility_rules', type_='unique')
    op.drop_table('field_visibility_rules')
