"""Rename legacy form tables to legacy_ prefix

All five tables created by migrations 0037 and 0053 are renamed to
legacy_* so the new Form Builder module can claim the canonical names
(form_schemas, form_schema_versions, field_definitions, form_associations,
form_submissions) with its own, richer schema.

Existing foreign-key constraints pointing TO these tables are updated
automatically by PostgreSQL (FK references store OIDs, not names).
Indexes are explicitly renamed to prevent name collisions when the new
tables create indexes with the same logical names.

Revision ID: 0076
Revises: 0075
Create Date: 2026-05-18
"""

from alembic import op

revision      = '0076'
down_revision = '0075'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── Rename tables ─────────────────────────────────────────
    op.rename_table('form_schemas',            'legacy_form_schemas')
    op.rename_table('form_fields',             'legacy_form_fields')
    op.rename_table('form_field_dependencies', 'legacy_form_field_dependencies')
    op.rename_table('form_submissions',        'legacy_form_submissions')
    op.rename_table('field_definitions',       'legacy_field_definitions')

    # ── Rename indexes (PostgreSQL keeps index names on table rename) ──
    # legacy_form_schemas
    op.execute("ALTER INDEX IF EXISTS ix_form_schemas_tenant_context  RENAME TO ix_legacy_form_schemas_tenant_context")
    op.execute("ALTER INDEX IF EXISTS ix_form_schemas_tenant_active   RENAME TO ix_legacy_form_schemas_tenant_active")

    # legacy_form_fields
    op.execute("ALTER INDEX IF EXISTS ix_form_fields_schema_order     RENAME TO ix_legacy_form_fields_schema_order")

    # legacy_form_field_dependencies
    op.execute("ALTER INDEX IF EXISTS ix_form_deps_schema             RENAME TO ix_legacy_form_deps_schema")

    # legacy_form_submissions
    op.execute("ALTER INDEX IF EXISTS ix_form_submissions_entity      RENAME TO ix_legacy_form_submissions_entity")
    op.execute("ALTER INDEX IF EXISTS ix_form_submissions_tenant      RENAME TO ix_legacy_form_submissions_tenant")

    # legacy_field_definitions
    op.execute("ALTER INDEX IF EXISTS ix_field_definitions_schema_order           RENAME TO ix_legacy_field_definitions_schema_order")
    op.execute("ALTER INDEX IF EXISTS ix_field_definitions_tenant                 RENAME TO ix_legacy_field_definitions_tenant")
    op.execute("ALTER INDEX IF EXISTS ix_field_definitions_validation_rules_gin   RENAME TO ix_legacy_field_definitions_validation_rules_gin")


def downgrade() -> None:
    # Rename indexes back first
    op.execute("ALTER INDEX IF EXISTS ix_legacy_field_definitions_validation_rules_gin  RENAME TO ix_field_definitions_validation_rules_gin")
    op.execute("ALTER INDEX IF EXISTS ix_legacy_field_definitions_tenant               RENAME TO ix_field_definitions_tenant")
    op.execute("ALTER INDEX IF EXISTS ix_legacy_field_definitions_schema_order         RENAME TO ix_field_definitions_schema_order")
    op.execute("ALTER INDEX IF EXISTS ix_legacy_form_submissions_tenant                RENAME TO ix_form_submissions_tenant")
    op.execute("ALTER INDEX IF EXISTS ix_legacy_form_submissions_entity                RENAME TO ix_form_submissions_entity")
    op.execute("ALTER INDEX IF EXISTS ix_legacy_form_deps_schema                       RENAME TO ix_form_deps_schema")
    op.execute("ALTER INDEX IF EXISTS ix_legacy_form_fields_schema_order               RENAME TO ix_form_fields_schema_order")
    op.execute("ALTER INDEX IF EXISTS ix_legacy_form_schemas_tenant_active             RENAME TO ix_form_schemas_tenant_active")
    op.execute("ALTER INDEX IF EXISTS ix_legacy_form_schemas_tenant_context            RENAME TO ix_form_schemas_tenant_context")

    # Rename tables back
    op.rename_table('legacy_field_definitions',       'field_definitions')
    op.rename_table('legacy_form_submissions',        'form_submissions')
    op.rename_table('legacy_form_field_dependencies', 'form_field_dependencies')
    op.rename_table('legacy_form_fields',             'form_fields')
    op.rename_table('legacy_form_schemas',            'form_schemas')
