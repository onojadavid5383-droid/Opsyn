"""Form Builder Phase 1 — create form_schema_versions

Immutable version snapshots. Once a schema is published, a version record
is created with field_snapshot — a complete JSONB copy of all field
definitions at that moment. Old submissions always reference their exact
version, so they can be re-rendered correctly even after schema changes.

field_snapshot carries a GIN index for fast JSONB introspection queries.

Plan reference: §3.3

Revision ID: 0078
Revises: 0077
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0078'
down_revision = '0077'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        'form_schema_versions',
        sa.Column('id',             postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('schema_id',      postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('form_schemas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id',      postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('published_at',   sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_by',   postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        # Immutable JSONB snapshot of all field definitions at publish time
        sa.Column('field_snapshot', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default='[]'),
        sa.Column('changelog',      sa.Text(), nullable=True),
        # Only one version per schema is marked current
        sa.Column('is_current',     sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at',     sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('created_by',     postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )

    # GIN index on field_snapshot enables fast JSONB field-key lookups
    op.create_index(
        'ix_fb_form_schema_versions_field_snapshot_gin',
        'form_schema_versions',
        ['field_snapshot'],
        postgresql_using='gin',
    )

    op.create_index(
        'ix_fb_form_schema_versions_schema_current',
        'form_schema_versions',
        ['schema_id', 'is_current'],
    )

    op.create_index(
        'ix_fb_form_schema_versions_tenant',
        'form_schema_versions',
        ['tenant_id'],
    )

    # Enforce: only one version per schema can be current
    op.create_index(
        'uq_fb_form_schema_versions_one_current',
        'form_schema_versions',
        ['schema_id'],
        unique=True,
        postgresql_where=sa.text('is_current = true'),
    )

    # RLS: tenant isolation
    op.execute("ALTER TABLE form_schema_versions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE form_schema_versions FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON form_schema_versions
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON form_schema_versions")
    op.execute("ALTER TABLE form_schema_versions DISABLE ROW LEVEL SECURITY")
    op.drop_index('uq_fb_form_schema_versions_one_current',          table_name='form_schema_versions')
    op.drop_index('ix_fb_form_schema_versions_tenant',               table_name='form_schema_versions')
    op.drop_index('ix_fb_form_schema_versions_schema_current',       table_name='form_schema_versions')
    op.drop_index('ix_fb_form_schema_versions_field_snapshot_gin',   table_name='form_schema_versions')
    op.drop_table('form_schema_versions')
