"""
OPSYN DEPARTMENT-DRIVEN RBAC — MIGRATION 0030
Creates three tables for the department-based permission system:
  feature_permissions     — global permission key registry (not tenant-scoped)
  department_feature_grants — tenant-scoped grant: dept + feature + min_role_level
  role_feature_overrides  — tenant-scoped role-level override per feature

This replaces the blunt require_role(N) approach with:
  Access = Role Level × Department Membership × Explicit Grants

Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0030'
down_revision = '0029'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── feature_permissions — global registry, not tenant-scoped ──
    op.create_table(
        'feature_permissions',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text('gen_random_uuid()'),
        ),
        sa.Column('feature_key',   sa.String(80),  nullable=False),
        sa.Column('feature_label', sa.String(200), nullable=False),
        sa.Column('module',        sa.String(50),  nullable=False),
        sa.Column('description',   sa.Text(),      nullable=True),
    )
    op.create_index('ix_feature_permissions_key', 'feature_permissions', ['feature_key'], unique=True)

    # ── department_feature_grants — tenant-scoped ─────────────
    op.create_table(
        'department_feature_grants',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text('gen_random_uuid()'),
        ),
        sa.Column('tenant_id',      postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('department_id',  postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('feature_key',    sa.String(80),  nullable=False),
        sa.Column('min_role_level', sa.Integer(),   nullable=False, server_default='1'),
        sa.Column('granted_by',     postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            'granted_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_foreign_key(
        'fk_dept_feature_grants_tenant',
        'department_feature_grants', 'tenants',
        ['tenant_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_dept_feature_grants_dept',
        'department_feature_grants', 'departments',
        ['department_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_dept_feature_grants_granted_by',
        'department_feature_grants', 'users',
        ['granted_by'], ['id'], ondelete='SET NULL',
    )
    op.create_unique_constraint(
        'uq_dept_feature_grant',
        'department_feature_grants',
        ['tenant_id', 'department_id', 'feature_key'],
    )
    op.create_index('ix_dept_feature_grants_tenant', 'department_feature_grants', ['tenant_id'])
    op.create_index('ix_dept_feature_grants_dept',   'department_feature_grants', ['department_id'])

    # Enable RLS on department_feature_grants
    op.execute("ALTER TABLE department_feature_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE department_feature_grants FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON department_feature_grants
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)

    # ── role_feature_overrides — tenant-scoped ────────────────
    op.create_table(
        'role_feature_overrides',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text('gen_random_uuid()'),
        ),
        sa.Column('tenant_id',   postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role_id',     postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('feature_key', sa.String(80),  nullable=False),
        sa.Column('is_granted',  sa.Boolean(),   nullable=False, server_default='false'),
    )
    op.create_foreign_key(
        'fk_role_feature_overrides_tenant',
        'role_feature_overrides', 'tenants',
        ['tenant_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_role_feature_overrides_role',
        'role_feature_overrides', 'roles',
        ['role_id'], ['id'], ondelete='CASCADE',
    )
    op.create_unique_constraint(
        'uq_role_feature_override',
        'role_feature_overrides',
        ['tenant_id', 'role_id', 'feature_key'],
    )
    op.create_index('ix_role_feature_overrides_tenant', 'role_feature_overrides', ['tenant_id'])

    # Enable RLS on role_feature_overrides
    op.execute("ALTER TABLE role_feature_overrides ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE role_feature_overrides FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON role_feature_overrides
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)

    # Seed feature_permissions with all 12 FTTx feature keys
    op.execute("""
        INSERT INTO feature_permissions (feature_key, feature_label, module, description) VALUES
        ('staff.create',       'Create Staff',             'staff',          'Create new staff members'),
        ('onboarding.manage',  'Manage Onboarding',        'onboarding',     'Review and approve onboarding requests'),
        ('outage.log',         'Log Outages',              'outage',         'Report new outage incidents'),
        ('outage.manage',      'Manage Outages',           'outage',         'Update and resolve outage incidents'),
        ('infrastructure.view','View Infrastructure',      'infrastructure', 'View infrastructure map and status'),
        ('infrastructure.edit','Edit Infrastructure',      'infrastructure', 'Add/edit infrastructure sites and routes'),
        ('leads.manage',       'Manage Leads',             'projects',       'Create and manage sales leads'),
        ('tasks.manage',       'Manage Tasks',             'tasks',          'Create, assign, and update tasks'),
        ('reports.view',       'View Reports',             'reports',        'Access operational reports'),
        ('reports.financial',  'View Financial Reports',   'reports',        'Access financial and cost reports'),
        ('pipeline.advance',   'Advance Pipeline',         'projects',       'Move projects through pipeline stages'),
        ('settings.admin',     'Administration Settings',  'settings',       'Configure system settings')
        ON CONFLICT (feature_key) DO NOTHING;
    """)


def downgrade() -> None:
    # Drop role_feature_overrides
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON role_feature_overrides")
    op.drop_index('ix_role_feature_overrides_tenant', table_name='role_feature_overrides')
    op.drop_constraint('uq_role_feature_override', 'role_feature_overrides', type_='unique')
    op.drop_constraint('fk_role_feature_overrides_role',   'role_feature_overrides', type_='foreignkey')
    op.drop_constraint('fk_role_feature_overrides_tenant', 'role_feature_overrides', type_='foreignkey')
    op.drop_table('role_feature_overrides')

    # Drop department_feature_grants
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON department_feature_grants")
    op.drop_index('ix_dept_feature_grants_dept',   table_name='department_feature_grants')
    op.drop_index('ix_dept_feature_grants_tenant', table_name='department_feature_grants')
    op.drop_constraint('uq_dept_feature_grant', 'department_feature_grants', type_='unique')
    op.drop_constraint('fk_dept_feature_grants_granted_by', 'department_feature_grants', type_='foreignkey')
    op.drop_constraint('fk_dept_feature_grants_dept',       'department_feature_grants', type_='foreignkey')
    op.drop_constraint('fk_dept_feature_grants_tenant',     'department_feature_grants', type_='foreignkey')
    op.drop_table('department_feature_grants')

    # Drop feature_permissions
    op.drop_index('ix_feature_permissions_key', table_name='feature_permissions')
    op.drop_table('feature_permissions')
