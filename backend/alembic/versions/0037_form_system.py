"""
OPSYN DYNAMIC FORM BUILDER — MIGRATION 0037
Sprint 3 Stage 1 — S3.1.1

Creates:
  form_schemas            — tenant-scoped schema definition (context × version)
  form_fields             — ordered field definitions with validation rules
  form_field_dependencies — conditional show/hide/require rules between fields
  form_submissions        — persisted submission data linked to an entity

Adds:
  projects.form_submission_id  UUID (nullable) FK → form_submissions.id
  FK constraint on tasks.form_submission_id → form_submissions.id
    (column was added in 0034 without FK; FK is applied here)

RLS: tenant_isolation policy on all four new tables.

Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0037'
down_revision = '0036'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── form_schemas ──────────────────────────────────────────
    op.create_table(
        'form_schemas',
        sa.Column('id',           postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',    postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('context',      sa.String(50),  nullable=False),
        sa.Column('version',      sa.Integer(),   nullable=False, server_default='1'),
        sa.Column('is_published', sa.Boolean(),   nullable=False, server_default='false'),
        sa.Column('title',        sa.String(200), nullable=False),
        sa.Column('description',  sa.Text(),      nullable=True),
        sa.Column('created_by',   postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at',   sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at',   sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_form_schemas_tenant_context', 'form_schemas', ['tenant_id', 'context'])

    # ── form_fields ───────────────────────────────────────────
    op.create_table(
        'form_fields',
        sa.Column('id',               postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',        postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('schema_id',        postgresql.UUID(as_uuid=True), sa.ForeignKey('form_schemas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('field_key',        sa.String(100), nullable=False),
        sa.Column('field_type',       sa.String(50),  nullable=False),
        sa.Column('label',            sa.String(200), nullable=False),
        sa.Column('placeholder',      sa.Text(),      nullable=True),
        sa.Column('help_text',        sa.Text(),      nullable=True),
        sa.Column('required',         sa.Boolean(),   nullable=False, server_default='false'),
        sa.Column('field_order',      sa.Integer(),   nullable=False, server_default='0'),
        sa.Column('options',          postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('validation_rules', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at',       sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_unique_constraint('uq_form_fields_schema_key', 'form_fields', ['schema_id', 'field_key'])
    op.create_index('ix_form_fields_schema_order', 'form_fields', ['schema_id', 'field_order'])

    # ── form_field_dependencies ───────────────────────────────
    op.create_table(
        'form_field_dependencies',
        sa.Column('id',                 postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',          postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('schema_id',          postgresql.UUID(as_uuid=True), sa.ForeignKey('form_schemas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_field_key',   sa.String(100), nullable=False),
        sa.Column('target_field_key',   sa.String(100), nullable=False),
        sa.Column('condition_operator', sa.String(50),  nullable=False),
        sa.Column('condition_value',    sa.Text(),      nullable=True),
        sa.Column('action',             sa.String(20),  nullable=False),
    )
    op.create_index('ix_form_deps_schema', 'form_field_dependencies', ['schema_id'])

    # ── form_submissions ──────────────────────────────────────
    op.create_table(
        'form_submissions',
        sa.Column('id',             postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',      postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('schema_id',      postgresql.UUID(as_uuid=True), sa.ForeignKey('form_schemas.id'), nullable=False),
        sa.Column('entity_type',    sa.String(50),  nullable=True),
        sa.Column('entity_id',      postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('submitted_by',   postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('submitted_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('submitted_at',   sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_form_submissions_entity', 'form_submissions', ['entity_type', 'entity_id'])
    op.create_index('ix_form_submissions_tenant', 'form_submissions', ['tenant_id'])

    # ── RLS on all four tables ────────────────────────────────
    for table in ('form_schemas', 'form_fields', 'form_field_dependencies', 'form_submissions'):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::uuid
                OR current_setting('app.tenant_id', TRUE) IS NULL
                OR current_setting('app.tenant_id', TRUE) = ''
            )
        """)

    # ── tasks.form_submission_id FK (column from 0034) ────────
    op.create_foreign_key(
        'fk_tasks_form_submission_id',
        'tasks', 'form_submissions',
        ['form_submission_id'], ['id'],
        ondelete='SET NULL',
    )

    # ── projects.form_submission_id ───────────────────────────
    op.add_column(
        'projects',
        sa.Column('form_submission_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_projects_form_submission_id',
        'projects', 'form_submissions',
        ['form_submission_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_projects_form_submission_id', 'projects', type_='foreignkey')
    op.drop_column('projects', 'form_submission_id')

    op.drop_constraint('fk_tasks_form_submission_id', 'tasks', type_='foreignkey')

    for table in reversed(('form_schemas', 'form_fields', 'form_field_dependencies', 'form_submissions')):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index('ix_form_submissions_tenant',    table_name='form_submissions')
    op.drop_index('ix_form_submissions_entity',    table_name='form_submissions')
    op.drop_index('ix_form_deps_schema',           table_name='form_field_dependencies')
    op.drop_index('ix_form_fields_schema_order',   table_name='form_fields')
    op.drop_constraint('uq_form_fields_schema_key','form_fields', type_='unique')
    op.drop_index('ix_form_schemas_tenant_context', table_name='form_schemas')

    op.drop_table('form_submissions')
    op.drop_table('form_field_dependencies')
    op.drop_table('form_fields')
    op.drop_table('form_schemas')
