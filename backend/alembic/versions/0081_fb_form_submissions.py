"""Form Builder Phase 1 — create form_submissions with GIN indexes

The data layer. Every form submission is stored here as JSONB, linked to
the exact schema version it was validated against (schema_version_id) and
the entity it describes (entity_type + entity_id).

schema_version_id is immutable — even if the schema changes later, the
stored submission always references the version it was submitted under,
guaranteeing historical re-rendering correctness.

Indexes per §3.9:
  GIN on data                                   — fast JSONB field-value queries
  (schema_id, entity_id, tenant_id)             — fastest lookup pattern
  (entity_type, entity_id, tenant_id)           — all forms for entity X
  (schema_id, schema_version_id, submitted_at)  — version-aware time-series

Plan reference: §3.9

Revision ID: 0081
Revises: 0080
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0081'
down_revision = '0080'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        'form_submissions',
        sa.Column('id',                postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',         postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('schema_id',         postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('form_schemas.id', ondelete='RESTRICT'), nullable=False),
        # Immutable reference to the exact version at time of submission
        sa.Column('schema_version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('form_schema_versions.id', ondelete='RESTRICT'), nullable=False),
        # 'customer' | 'project' | 'infrastructure_asset' | 'pipeline_stage' | 'standalone'
        sa.Column('entity_type',       sa.String(50),  nullable=False),
        sa.Column('entity_id',         postgresql.UUID(as_uuid=True), nullable=True),
        # Which association triggered this submission (nullable for ad-hoc submissions)
        sa.Column('association_id',    postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('form_associations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('submitted_by',      postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('submitted_at',      sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        # 'draft' | 'submitted' | 'approved' | 'rejected'
        sa.Column('status',            sa.String(20),  nullable=False, server_default='submitted'),
        # Actual field values: { field_key: value, ... }
        sa.Column('data',              postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default='{}'),
        # Auto-saved draft values before final submission
        sa.Column('draft_data',        postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('approved_by',       postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_at',       sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason',  sa.Text(), nullable=True),
        sa.Column('is_deleted',        sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at',        sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at',        sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('created_by',        postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )

    # GIN index on data — enables fast JSONB field-value queries across submissions
    op.create_index(
        'ix_fb_form_submissions_data_gin',
        'form_submissions',
        ['data'],
        postgresql_using='gin',
    )

    # Composite: (schema_id, entity_id, tenant_id) — fastest lookup pattern
    op.create_index(
        'ix_fb_form_submissions_schema_entity_tenant',
        'form_submissions',
        ['schema_id', 'entity_id', 'tenant_id'],
    )

    # Composite: (entity_type, entity_id, tenant_id) — all forms for entity X
    op.create_index(
        'ix_fb_form_submissions_entity_type_id_tenant',
        'form_submissions',
        ['entity_type', 'entity_id', 'tenant_id'],
    )

    # Composite: (schema_id, schema_version_id, submitted_at) — version-aware time-series
    op.create_index(
        'ix_fb_form_submissions_schema_version_time',
        'form_submissions',
        ['schema_id', 'schema_version_id', 'submitted_at'],
    )

    op.create_index(
        'ix_fb_form_submissions_tenant_status',
        'form_submissions',
        ['tenant_id', 'status'],
    )

    # RLS: tenant isolation
    op.execute("ALTER TABLE form_submissions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE form_submissions FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON form_submissions
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON form_submissions")
    op.execute("ALTER TABLE form_submissions DISABLE ROW LEVEL SECURITY")
    op.drop_index('ix_fb_form_submissions_tenant_status',           table_name='form_submissions')
    op.drop_index('ix_fb_form_submissions_schema_version_time',     table_name='form_submissions')
    op.drop_index('ix_fb_form_submissions_entity_type_id_tenant',   table_name='form_submissions')
    op.drop_index('ix_fb_form_submissions_schema_entity_tenant',    table_name='form_submissions')
    op.drop_index('ix_fb_form_submissions_data_gin',                table_name='form_submissions')
    op.drop_table('form_submissions')
