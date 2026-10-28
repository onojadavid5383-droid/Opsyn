"""
OPSYN MULTI-TENANT ISOLATION — ADD TENANT_ID TO ALL TABLES
Revision: 0028

Adds tenant_id UUID FK to all 14 existing tables:
  users, staff_profiles, departments, teams, regions, roles,
  user_scopes, tasks, projects, outage_incidents, notifications,
  audit_logs, pipeline_templates, dept_workflows

Strategy:
  1. Add tenant_id as nullable
  2. Backfill all existing rows with DEV_TENANT_UUID
  3. Set NOT NULL constraint
  4. Update UNIQUE constraints on departments.name and roles.name
     → UNIQUE(tenant_id, name) instead of global unique

Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0028'
down_revision = '0027'
branch_labels = None
depends_on    = None

DEV_TENANT_UUID = '00000000-0000-0000-0000-000000000001'

TABLES_WITH_TENANT = [
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
    # Step 1 — Add nullable tenant_id to all tables
    for table in TABLES_WITH_TENANT:
        op.add_column(
            table,
            sa.Column(
                'tenant_id',
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )

    # Step 2 — Backfill all existing rows with DEV_TENANT_UUID
    for table in TABLES_WITH_TENANT:
        op.execute(f"UPDATE {table} SET tenant_id = '{DEV_TENANT_UUID}' WHERE tenant_id IS NULL")

    # Step 3 — Add FK constraints and NOT NULL
    for table in TABLES_WITH_TENANT:
        # NOT NULL
        op.alter_column(table, 'tenant_id', nullable=False)
        # FK to tenants
        op.create_foreign_key(
            f'fk_{table}_tenant_id',
            table, 'tenants',
            ['tenant_id'], ['id'],
            ondelete='CASCADE',
        )
        # Index for fast tenant-scoped queries
        op.create_index(f'ix_{table}_tenant_id', table, ['tenant_id'])

    # Step 4 — Fix UNIQUE constraints on departments and roles
    # departments: drop UNIQUE(name), add UNIQUE(tenant_id, name)
    op.drop_constraint('departments_name_key', 'departments', type_='unique')
    op.create_unique_constraint(
        'uq_departments_tenant_name', 'departments', ['tenant_id', 'name']
    )

    # roles: drop UNIQUE(name), add UNIQUE(tenant_id, name)
    op.drop_constraint('roles_name_key', 'roles', type_='unique')
    op.create_unique_constraint(
        'uq_roles_tenant_name', 'roles', ['tenant_id', 'name']
    )

    # regions: drop UNIQUE(name) and UNIQUE(code), add tenant-scoped ones
    op.drop_constraint('regions_name_key', 'regions', type_='unique')
    op.drop_constraint('regions_code_key', 'regions', type_='unique')
    op.create_unique_constraint(
        'uq_regions_tenant_name', 'regions', ['tenant_id', 'name']
    )
    op.create_unique_constraint(
        'uq_regions_tenant_code', 'regions', ['tenant_id', 'code']
    )


def downgrade() -> None:
    # Restore original unique constraints
    op.drop_constraint('uq_regions_tenant_code', 'regions', type_='unique')
    op.drop_constraint('uq_regions_tenant_name', 'regions', type_='unique')
    op.create_unique_constraint('regions_code_key', 'regions', ['code'])
    op.create_unique_constraint('regions_name_key', 'regions', ['name'])

    op.drop_constraint('uq_roles_tenant_name', 'roles', type_='unique')
    op.create_unique_constraint('roles_name_key', 'roles', ['name'])

    op.drop_constraint('uq_departments_tenant_name', 'departments', type_='unique')
    op.create_unique_constraint('departments_name_key', 'departments', ['name'])

    # Remove tenant_id from all tables
    for table in reversed(TABLES_WITH_TENANT):
        op.drop_index(f'ix_{table}_tenant_id', table_name=table)
        op.drop_constraint(f'fk_{table}_tenant_id', table, type_='foreignkey')
        op.drop_column(table, 'tenant_id')
