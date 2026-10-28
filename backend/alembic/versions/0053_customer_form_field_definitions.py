"""Customer Module Phase 1 — extend form_schemas + create field_definitions

Extends form_schemas with customer-pipeline columns (is_active, department_id).
Creates field_definitions table: richer customer-aware field definitions with
pipeline-stage visibility and department ownership.

Revision ID: 0053
Revises: 0052
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0053'
down_revision = '0052'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extend form_schemas ───────────────────────────────────
    # is_active mirrors is_published for customer-module queries
    op.add_column(
        'form_schemas',
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='false'),
    )
    # department_id scopes a schema to a specific department (null = global)
    op.add_column(
        'form_schemas',
        sa.Column('department_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_form_schemas_department_id',
        'form_schemas', 'departments',
        ['department_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_form_schemas_tenant_active',
        'form_schemas',
        ['tenant_id', 'is_active'],
    )

    # ── field_definitions ─────────────────────────────────────
    # Separate from form_fields — customer-pipeline aware with stage visibility
    op.create_table(
        'field_definitions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('form_schema_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('form_schemas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('key', sa.String(100), nullable=False),
        sa.Column('label', sa.String(200), nullable=False),
        sa.Column('field_type', sa.String(50), nullable=False),
        sa.Column('validation_rules', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('owner_department_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('departments.id', ondelete='SET NULL'), nullable=True),
        # Stage order at which this field first becomes visible in the pipeline UI
        sa.Column('visible_from_stage_order', sa.Integer(), nullable=False, server_default='1'),
        # ARRAY of role names allowed to edit this field (e.g. ['admin', 'manager'])
        sa.Column('roles_can_edit', postgresql.ARRAY(sa.Text()), nullable=False,
                  server_default='{}'),
        sa.Column('field_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    op.create_unique_constraint(
        'uq_field_definitions_schema_key',
        'field_definitions',
        ['form_schema_id', 'key'],
    )
    op.create_index(
        'ix_field_definitions_schema_order',
        'field_definitions',
        ['form_schema_id', 'field_order'],
    )
    op.create_index(
        'ix_field_definitions_tenant',
        'field_definitions',
        ['tenant_id'],
    )
    # GIN index for validation_rules JSONB
    op.create_index(
        'ix_field_definitions_validation_rules_gin',
        'field_definitions',
        ['validation_rules'],
        postgresql_using='gin',
    )


def downgrade() -> None:
    op.drop_index('ix_field_definitions_validation_rules_gin', table_name='field_definitions')
    op.drop_index('ix_field_definitions_tenant', table_name='field_definitions')
    op.drop_index('ix_field_definitions_schema_order', table_name='field_definitions')
    op.drop_constraint('uq_field_definitions_schema_key', 'field_definitions', type_='unique')
    op.drop_table('field_definitions')

    op.drop_index('ix_form_schemas_tenant_active', table_name='form_schemas')
    op.drop_constraint('fk_form_schemas_department_id', 'form_schemas', type_='foreignkey')
    op.drop_column('form_schemas', 'department_id')
    op.drop_column('form_schemas', 'is_active')
