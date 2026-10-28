"""Infrastructure Management — Phase 1 (8/8): RLS + GiST/GIN spatial indexes

Enables Row Level Security on all 7 new infrastructure tables.
Adds GiST spatial indexes on geometry(Point,4326) columns for map queries.
Adds GIN indexes on JSONB audit columns.

Revision ID: 0074
Revises: 0073
Create Date: 2026-05-17
"""

from alembic import op

revision      = '0074'
down_revision = '0073'
branch_labels = None
depends_on    = None

# Tables that carry tenant_id and need RLS
_TENANT_TABLES = [
    'infrastructure_upload_sessions',
    'infrastructure_deletion_sessions',
    'infrastructure_upload_staging',
    'infrastructure_audit_log',
    'cabinets',
    'olts',
    'splitter_boxes',
]

# Geometry tables needing GiST spatial index
_GEOMETRY_TABLES = ['cabinets', 'olts', 'splitter_boxes']

# Audit log JSONB columns needing GIN indexes
_AUDIT_JSONB_COLS = ['old_data', 'new_data']


def upgrade() -> None:
    # ── RLS on all new tenant-scoped tables ──────────────────────
    for table in _TENANT_TABLES:
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

    # ── GiST spatial indexes on geometry columns ─────────────────
    for table in _GEOMETRY_TABLES:
        op.execute(f"""
            CREATE INDEX ix_{table}_location_gist
            ON {table} USING GIST (location)
        """)

    # ── GIN indexes on audit log JSONB columns ───────────────────
    for col in _AUDIT_JSONB_COLS:
        op.execute(f"""
            CREATE INDEX ix_infra_audit_{col}_gin
            ON infrastructure_audit_log USING GIN ({col})
            WHERE {col} IS NOT NULL
        """)


def downgrade() -> None:
    for col in _AUDIT_JSONB_COLS:
        op.execute(
            f"DROP INDEX IF EXISTS ix_infra_audit_{col}_gin"
        )

    for table in _GEOMETRY_TABLES:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_location_gist")

    for table in reversed(_TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
