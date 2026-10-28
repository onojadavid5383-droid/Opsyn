"""Form Builder Phase 1 — create form_schemas registry

The canonical schema registry for the Form Builder system.
Replaces the legacy_form_schemas table with a richer, versioned,
module-aware structure per the FormBuilder Implementation Plan §3.2.

Every tenant owns their own schema set. machine_name is stable across
versions and must be unique per tenant (partial unique where not deleted).

Revision ID: 0077
Revises: 0076
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0077'
down_revision = '0076'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        'form_schemas',
        sa.Column('id',              postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',       postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name',            sa.String(200), nullable=False),
        sa.Column('machine_name',    sa.String(100), nullable=False),
        sa.Column('description',     sa.Text(),      nullable=True),
        sa.Column('module',          sa.String(50),  nullable=False),
        sa.Column('status',          sa.String(20),  nullable=False, server_default='draft'),
        sa.Column('current_version', sa.Integer(),   nullable=False, server_default='0'),
        sa.Column('icon',            sa.String(50),  nullable=True),
        sa.Column('color',           sa.String(7),   nullable=True),
        sa.Column('is_deleted',      sa.Boolean(),   nullable=False, server_default='false'),
        sa.Column('created_at',      sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at',      sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('created_by',      postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )

    # Partial unique: machine_name must be unique per tenant among non-deleted schemas
    op.create_index(
        'uq_fb_form_schemas_machine_name_tenant',
        'form_schemas',
        ['machine_name', 'tenant_id'],
        unique=True,
        postgresql_where=sa.text('is_deleted = false'),
    )

    op.create_index('ix_fb_form_schemas_tenant_status',  'form_schemas', ['tenant_id', 'status'])
    op.create_index('ix_fb_form_schemas_tenant_module',  'form_schemas', ['tenant_id', 'module'])

    # RLS: tenant isolation
    op.execute("ALTER TABLE form_schemas ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE form_schemas FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON form_schemas
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON form_schemas")
    op.execute("ALTER TABLE form_schemas DISABLE ROW LEVEL SECURITY")
    op.drop_index('ix_fb_form_schemas_tenant_module',      table_name='form_schemas')
    op.drop_index('ix_fb_form_schemas_tenant_status',      table_name='form_schemas')
    op.drop_index('uq_fb_form_schemas_machine_name_tenant', table_name='form_schemas')
    op.drop_table('form_schemas')
