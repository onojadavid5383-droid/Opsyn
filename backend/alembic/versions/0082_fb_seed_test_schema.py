"""Form Builder Phase 1 — seed test schema for Phase 2 unit tests

Creates one 'Test Customer Form' schema with 5 field definitions of
different types so Phase 2 validation engine unit tests have a real
schema to run against without needing a UI.

The seed schema is tenant-agnostic (no tenant_id — inserted as NULL
which is not allowed by the NOT NULL constraint). Instead, this migration
uses a fixed test-tenant UUID. The test suite must use this same UUID
when calling the validation engine in Phase 2 tests.

TEST_TENANT_ID  = '00000000-0000-0000-0000-000000000001'
TEST_SCHEMA_ID  = '00000000-0000-0000-0001-000000000001'
TEST_VERSION_ID = '00000000-0000-0000-0002-000000000001'

Note: this seed data is for development / test environments only.
Production environments already have a real tenant record; use the
admin UI to create production schemas.

Revision ID: 0082
Revises: 0081
Create Date: 2026-05-18
"""

import json

from alembic import op
import sqlalchemy as sa

revision      = '0082'
down_revision = '0081'
branch_labels = None
depends_on    = None

_TEST_TENANT  = '00000000-0000-0000-0000-000000000001'
_TEST_SCHEMA  = '00000000-0000-0000-0001-000000000001'
_TEST_VERSION = '00000000-0000-0000-0002-000000000001'


def upgrade() -> None:
    conn = op.get_bind()

    # Only seed if the test tenant exists (dev/test environments)
    tenant_exists = conn.execute(
        sa.text("SELECT 1 FROM tenants WHERE id = :tid"),
        {"tid": _TEST_TENANT},
    ).scalar_one_or_none()

    if not tenant_exists:
        return  # Skip seed in production where this tenant doesn't exist

    # ── Insert test form schema ───────────────────────────────
    conn.execute(sa.text("""
        INSERT INTO form_schemas
            (id, tenant_id, name, machine_name, description, module,
             status, current_version, is_deleted, created_at, updated_at)
        VALUES
            (:sid, :tid, 'Test Customer Form', 'test_customer_form',
             'Seeded by migration 0082 for Phase 2 unit tests',
             'customer', 'published', 1, false, now(), now())
        ON CONFLICT DO NOTHING
    """), {"sid": _TEST_SCHEMA, "tid": _TEST_TENANT})

    # ── Insert test schema version ────────────────────────────
    # Pass field_snapshot as a named parameter to avoid SQLAlchemy
    # misinterpreting JSON colons (e.g. ":0", ":true") as bind params.
    _snapshot = json.dumps([
        {"field_key": "full_name",        "label": "Full Name",        "field_type": "string",  "display_order": 0, "is_required": True,  "validation_rules": {"min_length": 2, "max_length": 100}},
        {"field_key": "age",              "label": "Age",              "field_type": "integer", "display_order": 1, "is_required": False, "validation_rules": {"min": 0, "max": 120}},
        {"field_key": "email",            "label": "Email Address",    "field_type": "email",   "display_order": 2, "is_required": True,  "validation_rules": {}},
        {"field_key": "account_type",     "label": "Account Type",     "field_type": "enum",    "display_order": 3, "is_required": True,  "options": [{"value": "residential", "label": "Residential"}, {"value": "business", "label": "Business"}], "validation_rules": {}},
        {"field_key": "installation_date","label": "Installation Date","field_type": "date",    "display_order": 4, "is_required": False, "validation_rules": {"no_past": False}},
    ])

    conn.execute(sa.text("""
        INSERT INTO form_schema_versions
            (id, schema_id, tenant_id, version_number, published_at,
             field_snapshot, changelog, is_current, created_at)
        VALUES
            (:vid, :sid, :tid, 1, now(),
             CAST(:snapshot AS JSONB),
             'Initial seeded version for Phase 2 unit tests',
             true, now())
        ON CONFLICT DO NOTHING
    """), {"vid": _TEST_VERSION, "sid": _TEST_SCHEMA, "tid": _TEST_TENANT, "snapshot": _snapshot})

    # ── Insert the 5 field definition rows ───────────────────
    fields = [
        (_TEST_SCHEMA, _TEST_VERSION, _TEST_TENANT,
         'full_name', 'Full Name', 'string', 0, True,
         '{"min_length":2,"max_length":100}', None),
        (_TEST_SCHEMA, _TEST_VERSION, _TEST_TENANT,
         'age', 'Age', 'integer', 1, False,
         '{"min":0,"max":120}', None),
        (_TEST_SCHEMA, _TEST_VERSION, _TEST_TENANT,
         'email', 'Email Address', 'email', 2, True,
         '{}', None),
        (_TEST_SCHEMA, _TEST_VERSION, _TEST_TENANT,
         'account_type', 'Account Type', 'enum', 3, True,
         '{}', '[{"value":"residential","label":"Residential"},{"value":"business","label":"Business"}]'),
        (_TEST_SCHEMA, _TEST_VERSION, _TEST_TENANT,
         'installation_date', 'Installation Date', 'date', 4, False,
         '{"no_past":false}', None),
    ]

    for schema_id, version_id, tenant_id, fkey, label, ftype, order, required, rules, opts in fields:
        conn.execute(sa.text("""
            INSERT INTO field_definitions
                (schema_id, schema_version_id, tenant_id, field_key, label,
                 field_type, display_order, is_required, validation_rules, options,
                 is_deleted, created_at, updated_at)
            VALUES
                (:sid, :vid, :tid, :fkey, :label,
                 :ftype, :order, :req, CAST(:rules AS JSONB),
                 CAST(:opts AS JSONB), false, now(), now())
            ON CONFLICT DO NOTHING
        """), {
            "sid": schema_id, "vid": version_id, "tid": tenant_id,
            "fkey": fkey, "label": label, "ftype": ftype,
            "order": order, "req": required, "rules": rules,
            "opts": opts,
        })


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM field_definitions    WHERE schema_id = :sid"), {"sid": _TEST_SCHEMA})
    conn.execute(sa.text("DELETE FROM form_schema_versions WHERE schema_id = :sid"), {"sid": _TEST_SCHEMA})
    conn.execute(sa.text("DELETE FROM form_schemas         WHERE id        = :sid"), {"sid": _TEST_SCHEMA})
