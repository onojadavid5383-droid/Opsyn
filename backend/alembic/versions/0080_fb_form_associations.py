"""Form Builder Phase 1 — create form_associations

The linking system that connects a form schema to its context: which module,
pipeline stage, department, external trigger, or user role uses this schema,
and under what conditions (mandatory, trigger event, display order).

One schema can have many associations. A pipeline stage can require many
schemas. context_id is NULL for wildcard associations (applies to all
instances of context_type).

Plan reference: §3.8

Revision ID: 0080
Revises: 0079
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0080'
down_revision = '0079'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        'form_associations',
        sa.Column('id',               postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',        postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('schema_id',        postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('form_schemas.id', ondelete='CASCADE'), nullable=False),
        # NULL = always use current version; non-NULL = pinned to a specific version
        sa.Column('schema_version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('form_schema_versions.id', ondelete='SET NULL'), nullable=True),
        # 'module' | 'pipeline_stage' | 'department' | 'external_trigger' | 'user_role'
        sa.Column('context_type',     sa.String(50),  nullable=False),
        # ID of the module, stage, dept, trigger — NULL for wildcard
        sa.Column('context_id',       postgresql.UUID(as_uuid=True), nullable=True),
        # Human-readable context name for display in the Association Manager UI
        sa.Column('context_label',    sa.String(200), nullable=False),
        # If TRUE, this form must be submitted before the context allows progression
        sa.Column('is_mandatory',     sa.Boolean(),   nullable=False, server_default='false'),
        sa.Column('display_order',    sa.SmallInteger(), nullable=False, server_default='0'),
        # 'on_create' | 'on_stage_enter' | 'on_approval' | 'manual'
        sa.Column('trigger_event',    sa.String(50),  nullable=True),
        # Map of field_key → system_value for auto-populate on form open
        sa.Column('auto_populate_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_deleted',       sa.Boolean(),   nullable=False, server_default='false'),
        sa.Column('created_at',       sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at',       sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('created_by',       postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )

    # Fast lookup: "all schemas for this context" — the key integration query
    op.create_index(
        'ix_fb_form_associations_context',
        'form_associations',
        ['context_type', 'context_id', 'tenant_id'],
    )

    op.create_index(
        'ix_fb_form_associations_schema',
        'form_associations',
        ['schema_id', 'tenant_id'],
    )

    op.create_index(
        'ix_fb_form_associations_tenant',
        'form_associations',
        ['tenant_id'],
    )

    # RLS: tenant isolation
    op.execute("ALTER TABLE form_associations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE form_associations FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON form_associations
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON form_associations")
    op.execute("ALTER TABLE form_associations DISABLE ROW LEVEL SECURITY")
    op.drop_index('ix_fb_form_associations_tenant',  table_name='form_associations')
    op.drop_index('ix_fb_form_associations_schema',  table_name='form_associations')
    op.drop_index('ix_fb_form_associations_context', table_name='form_associations')
    op.drop_table('form_associations')
