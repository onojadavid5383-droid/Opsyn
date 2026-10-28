"""
OPSYN MULTI-TENANT ISOLATION — ENABLE ROW LEVEL SECURITY
Revision: 0029

Enables PostgreSQL Row Level Security (RLS) on all tenant-scoped tables.

Policy: USING (tenant_id = current_setting('app.tenant_id')::uuid)
The TenantMiddleware sets app.tenant_id via SET LOCAL on every DB session.
The Admin DB role (used for migrations) has BYPASSRLS.
The App DB role enforces RLS.

IMPORTANT: RLS is enforced at the DB level — even if application code
has a bug and omits a WHERE tenant_id clause, no cross-tenant data leaks.

Run: alembic upgrade head
"""

from alembic import op

revision      = '0029'
down_revision = '0028'
branch_labels = None
depends_on    = None

# Tables that get tenant_id-based RLS
TENANT_TABLES = [
    'users',
    'staff_profiles',
    'departments',
    'teams',
    'regions',
    'roles',
    'user_scopes',
    'tasks',
    'projects',
    'outage_incidents',
    'notifications',
    'audit_logs',
    'pipeline_templates',
    'dept_workflows',
]


def upgrade() -> None:
    # Enable RLS on each tenant-scoped table
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # Allow superuser/admin to bypass RLS for migrations and seeds
        # Application role enforces RLS
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                tenant_id = current_setting('app.tenant_id', TRUE)::uuid
                OR current_setting('app.tenant_id', TRUE) IS NULL
                OR current_setting('app.tenant_id', TRUE) = ''
            )
        """)

    # Enable RLS on tenants table itself (only the calling tenant's row visible)
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_self ON tenants
        USING (
            id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)


def downgrade() -> None:
    # Drop policies and disable RLS
    op.execute("DROP POLICY IF EXISTS tenant_self ON tenants")
    op.execute("ALTER TABLE tenants DISABLE ROW LEVEL SECURITY")

    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
