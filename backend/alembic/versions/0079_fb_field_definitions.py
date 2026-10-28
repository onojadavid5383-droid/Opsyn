"""Form Builder Phase 1 — create field_definitions

The heart of the Form Builder system. Every field in every schema is a row
here. Fields belong to a schema (schema_id) and, once published, are also
linked to the schema version (schema_version_id) they were snapshot into.

Full column spec per §3.4 and §3.5. CHECK constraint enforces the 24
supported field types from the type catalogue (§3.5). Conditional logic
and validation rules are stored as JSONB per §3.6 and §3.7.

Plan reference: §3.4, §3.5, §3.6, §3.7

Revision ID: 0079
Revises: 0078
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0079'
down_revision = '0078'
branch_labels = None
depends_on    = None

_FIELD_TYPES = (
    'string', 'text', 'integer', 'float', 'boolean',
    'date', 'datetime', 'time', 'email', 'phone', 'url',
    'enum', 'multiselect', 'radio',
    'file', 'image',
    'coordinates', 'address', 'currency', 'rating', 'signature',
    'lookup', 'computed', 'section_header',
)


def upgrade() -> None:
    op.create_table(
        'field_definitions',
        sa.Column('id',               postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('schema_id',        postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('form_schemas.id', ondelete='CASCADE'), nullable=False),
        # Set when field is snapshotted into a published version; NULL while draft
        sa.Column('schema_version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('form_schema_versions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('tenant_id',        postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        # Machine key: stable across versions, used as JSONB data key
        sa.Column('field_key',        sa.String(100), nullable=False),
        sa.Column('label',            sa.String(200), nullable=False),
        sa.Column('placeholder',      sa.String(300), nullable=True),
        sa.Column('help_text',        sa.Text(),      nullable=True),
        sa.Column('field_type',       sa.String(30),  nullable=False),
        sa.Column('display_order',    sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('is_required',      sa.Boolean(),   nullable=False, server_default='false'),
        sa.Column('is_unique',        sa.Boolean(),   nullable=False, server_default='false'),
        sa.Column('is_readonly',      sa.Boolean(),   nullable=False, server_default='false'),
        sa.Column('is_hidden',        sa.Boolean(),   nullable=False, server_default='false'),
        sa.Column('default_value',    sa.Text(),      nullable=True),
        # Full validation config per §3.6 — all rules for this field
        sa.Column('validation_rules', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default='{}'),
        # For enum/multiselect/radio: [{value, label, color}]
        sa.Column('options',          postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Show/hide/require conditional logic per §3.7
        sa.Column('conditional_logic', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Role names that can see this field (NULL = all roles)
        sa.Column('role_visibility',  postgresql.ARRAY(sa.Text()), nullable=True),
        # Role names that can edit this field (NULL = all roles)
        sa.Column('role_editable',    postgresql.ARRAY(sa.Text()), nullable=True),
        # Pipeline stage order from which field becomes visible
        sa.Column('stage_visible_from', sa.SmallInteger(), nullable=True),
        # Pipeline stage order at which field becomes mandatory
        sa.Column('stage_required_at',  sa.SmallInteger(), nullable=True),
        # Department responsible for filling this field
        sa.Column('department_owner', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('departments.id', ondelete='SET NULL'), nullable=True),
        # Grid layout hint: 'full' | 'half' | 'third'
        sa.Column('width',            sa.String(10),  nullable=False, server_default='full'),
        # Groups fields under a collapsible section header
        sa.Column('section_group',    sa.String(100), nullable=True),
        sa.Column('is_deleted',       sa.Boolean(),   nullable=False, server_default='false'),
        sa.Column('created_at',       sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at',       sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('created_by',       postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )

    # CHECK constraint: field_type must be one of the 24 documented types
    field_type_list = ", ".join(f"'{t}'" for t in _FIELD_TYPES)
    op.execute(f"""
        ALTER TABLE field_definitions
        ADD CONSTRAINT ck_fb_field_definitions_field_type
        CHECK (field_type IN ({field_type_list}))
    """)

    # Unique field_key within a schema (among non-deleted fields in draft)
    op.create_index(
        'uq_fb_field_definitions_schema_key',
        'field_definitions',
        ['schema_id', 'field_key'],
        unique=True,
        postgresql_where=sa.text('is_deleted = false'),
    )

    op.create_index(
        'ix_fb_field_definitions_schema_order',
        'field_definitions',
        ['schema_id', 'display_order'],
    )

    op.create_index(
        'ix_fb_field_definitions_tenant',
        'field_definitions',
        ['tenant_id'],
    )

    op.create_index(
        'ix_fb_field_definitions_version',
        'field_definitions',
        ['schema_version_id'],
    )

    # RLS: tenant isolation
    op.execute("ALTER TABLE field_definitions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE field_definitions FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON field_definitions
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON field_definitions")
    op.execute("ALTER TABLE field_definitions DISABLE ROW LEVEL SECURITY")
    op.drop_index('ix_fb_field_definitions_version',       table_name='field_definitions')
    op.drop_index('ix_fb_field_definitions_tenant',        table_name='field_definitions')
    op.drop_index('ix_fb_field_definitions_schema_order',  table_name='field_definitions')
    op.drop_index('uq_fb_field_definitions_schema_key',    table_name='field_definitions')
    op.execute("ALTER TABLE field_definitions DROP CONSTRAINT IF EXISTS ck_fb_field_definitions_field_type")
    op.drop_table('field_definitions')
