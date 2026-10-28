"""
OPSYN INITIAL SCHEMA MIGRATION
Revision: 0001
Creates all tables from scratch.
Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── roles ────────────────────────────────────────────────
    op.create_table(
        'roles',
        sa.Column('id',             postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name',           sa.String(80),  unique=True, nullable=False),
        sa.Column('level',          sa.Integer(),   nullable=False),
        sa.Column('is_system_role', sa.Boolean(),   server_default='false'),
        sa.Column('description',    sa.Text()),
    )

    # ── regions ──────────────────────────────────────────────
    op.create_table(
        'regions',
        sa.Column('id',        postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name',      sa.String(100), unique=True, nullable=False),
        sa.Column('code',      sa.String(20),  unique=True, nullable=False),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('regions.id')),
    )

    # ── departments ──────────────────────────────────────────
    op.create_table(
        'departments',
        sa.Column('id',           postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name',         sa.String(150), unique=True, nullable=False),
        sa.Column('head_user_id', postgresql.UUID(as_uuid=True)),
        sa.Column('parent_id',    postgresql.UUID(as_uuid=True), sa.ForeignKey('departments.id')),
    )

    # ── teams ────────────────────────────────────────────────
    op.create_table(
        'teams',
        sa.Column('id',            postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name',          sa.String(150), nullable=False),
        sa.Column('department_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('departments.id'), nullable=False),
        sa.Column('lead_user_id',  postgresql.UUID(as_uuid=True)),
    )

    # ── users ────────────────────────────────────────────────
    op.create_table(
        'users',
        sa.Column('id',            postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('username',      sa.String(80),  unique=True, nullable=False),
        sa.Column('email',         sa.String(255), unique=True, nullable=False),
        sa.Column('password_hash', sa.Text(),      nullable=False),
        sa.Column('role_id',       postgresql.UUID(as_uuid=True), sa.ForeignKey('roles.id'), nullable=False),
        sa.Column('is_active',     sa.Boolean(),   server_default='true'),
        sa.Column('last_login_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('created_at',    sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',    sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_users_email',    'users', ['email'])
    op.create_index('ix_users_username', 'users', ['username'])

    # ── staff_profiles ───────────────────────────────────────
    op.create_table(
        'staff_profiles',
        sa.Column('id',                       postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id',                  postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), unique=True, nullable=False),
        sa.Column('staff_code',               sa.String(40), unique=True, nullable=False),
        sa.Column('first_name',               sa.String(100), nullable=False),
        sa.Column('last_name',                sa.String(100), nullable=False),
        sa.Column('phone',                    sa.String(30)),
        sa.Column('job_title',                sa.String(150)),
        sa.Column('skill_category',           sa.String(100)),
        sa.Column('specialization',           sa.String(150)),
        sa.Column('employment_type',          sa.String(20), server_default='permanent'),
        sa.Column('region_id',                postgresql.UUID(as_uuid=True), sa.ForeignKey('regions.id')),
        sa.Column('department_id',            postgresql.UUID(as_uuid=True), sa.ForeignKey('departments.id'), nullable=False),
        sa.Column('team_id',                  postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id')),
        sa.Column('manager_user_id',          postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('approval_authority_level', sa.Integer(), server_default='0'),
        sa.Column('olt_domain',               sa.String(200)),
        sa.Column('work_location',            sa.String(200)),
        sa.Column('outage_responsibility',    sa.Text()),
        sa.Column('mec_responsibility',       sa.Text()),
        sa.Column('status',                   sa.String(20), server_default='active'),
        sa.Column('notes',                    sa.Text()),
        sa.Column('joined_at',                sa.Date()),
        sa.Column('end_date',                 sa.Date()),
        sa.Column('created_by',               postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('created_at',               sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',               sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    # ── user_scopes ──────────────────────────────────────────
    op.create_table(
        'user_scopes',
        sa.Column('id',                 postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id',            postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('scope_type',         sa.String(20)),
        sa.Column('scope_reference_id', postgresql.UUID(as_uuid=True)),
        sa.Column('granted_by',         postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('created_at',         sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    # ── user_role_history ────────────────────────────────────
    op.create_table(
        'user_role_history',
        sa.Column('id',          postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id',     postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('old_role_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('roles.id')),
        sa.Column('new_role_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('roles.id')),
        sa.Column('changed_by',  postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('changed_at',  sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    # ── tasks ────────────────────────────────────────────────
    op.create_table(
        'tasks',
        sa.Column('id',               postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('title',            sa.String(300), nullable=False),
        sa.Column('description',      sa.Text()),
        sa.Column('priority',         sa.String(20), server_default='medium'),
        sa.Column('status',           sa.String(20), server_default='backlog'),
        sa.Column('deadline',         sa.TIMESTAMP(timezone=True)),
        sa.Column('department_id',    postgresql.UUID(as_uuid=True), sa.ForeignKey('departments.id')),
        sa.Column('project_id',       postgresql.UUID(as_uuid=True)),
        sa.Column('assignee_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('created_by',       postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('created_at',       sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',       sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_tasks_deadline', 'tasks', ['deadline'])
    op.create_index('ix_tasks_status',   'tasks', ['status'])

    # ── task_comments ────────────────────────────────────────
    op.create_table(
        'task_comments',
        sa.Column('id',             postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('task_id',        postgresql.UUID(as_uuid=True), sa.ForeignKey('tasks.id', ondelete='CASCADE')),
        sa.Column('author_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('body',           sa.Text(), nullable=False),
        sa.Column('created_at',     sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    # ── task_tags ────────────────────────────────────────────
    op.create_table(
        'task_tags',
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('tag',     sa.String(60), primary_key=True),
    )

    # ── projects ─────────────────────────────────────────────
    op.create_table(
        'projects',
        sa.Column('id',             postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name',           sa.String(200), nullable=False),
        sa.Column('description',    sa.Text()),
        sa.Column('status',         sa.String(20), server_default='active'),
        sa.Column('department_id',  postgresql.UUID(as_uuid=True), sa.ForeignKey('departments.id')),
        sa.Column('completion_pct', sa.Integer(), server_default='0'),
        sa.Column('due_date',       sa.Date()),
        sa.Column('created_at',     sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    # ── outage_incidents ─────────────────────────────────────
    op.create_table(
        'outage_incidents',
        sa.Column('id',            postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('reference',     sa.String(20), unique=True),
        sa.Column('title',         sa.String(200), nullable=False),
        sa.Column('description',   sa.Text()),
        sa.Column('severity',      sa.String(20), server_default='warning'),
        sa.Column('status',        sa.String(20), server_default='active'),
        sa.Column('region_id',     postgresql.UUID(as_uuid=True), sa.ForeignKey('regions.id')),
        sa.Column('olt_reference', sa.String(100)),
        sa.Column('reported_by',   postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('resolved_at',   sa.TIMESTAMP(timezone=True)),
        sa.Column('created_at',    sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',    sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    # ── staff_onboarding_requests ────────────────────────────
    op.create_table(
        'staff_onboarding_requests',
        sa.Column('id',                  postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('requested_by',        postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('proposed_first_name', sa.String(100), nullable=False),
        sa.Column('proposed_last_name',  sa.String(100), nullable=False),
        sa.Column('proposed_email',      sa.String(255), nullable=False),
        sa.Column('proposed_role_id',    postgresql.UUID(as_uuid=True), sa.ForeignKey('roles.id')),
        sa.Column('department_id',       postgresql.UUID(as_uuid=True), sa.ForeignKey('departments.id')),
        sa.Column('team_id',             postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id')),
        sa.Column('justification',       sa.Text()),
        sa.Column('approval_status',     sa.String(20), server_default='pending'),
        sa.Column('approved_by',         postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('approved_at',         sa.TIMESTAMP(timezone=True)),
        sa.Column('provisioned_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('created_at',          sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    # ── notifications ────────────────────────────────────────
    op.create_table(
        'notifications',
        sa.Column('id',           postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('recipient_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('type',         sa.String(50)),
        sa.Column('title',        sa.String(200), nullable=False),
        sa.Column('body',         sa.Text()),
        sa.Column('is_read',      sa.Boolean(), server_default='false'),
        sa.Column('action_url',   sa.String(500)),
        sa.Column('created_at',   sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_notifications_recipient', 'notifications', ['recipient_id'])

    # ── audit_logs ───────────────────────────────────────────
    op.create_table(
        'audit_logs',
        sa.Column('id',           postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('actor_id',     postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('action',       sa.String(100), nullable=False),
        sa.Column('target_type',  sa.String(80)),
        sa.Column('target_id',    postgresql.UUID(as_uuid=True)),
        sa.Column('before_state', postgresql.JSONB()),
        sa.Column('after_state',  postgresql.JSONB()),
        sa.Column('ip_address',   sa.String(45)),
        sa.Column('user_agent',   sa.Text()),
        sa.Column('created_at',   sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), index=True),
    )
    op.create_index('ix_audit_logs_action',     'audit_logs', ['action'])
    op.create_index('ix_audit_logs_actor',      'audit_logs', ['actor_id'])
    # Note: ix_audit_logs_created_at is already created via index=True on the column definition

    # ── Seed initial roles ───────────────────────────────────
    op.execute("""
        INSERT INTO roles (name, level, is_system_role) VALUES
        ('Staff',            1, true),
        ('NOC Operator',     2, true),
        ('MEC Reviewer',     2, true),
        ('Executive Viewer', 2, true),
        ('Team Lead',        3, true),
        ('Manager',          4, true),
        ('Admin',            5, true)
        ON CONFLICT (name) DO NOTHING;
    """)

    # ── Seed regions ─────────────────────────────────────────
    op.execute("""
        INSERT INTO regions (name, code) VALUES
        ('Lagos',         'LOS'),
        ('Abuja',         'ABJ'),
        ('Port Harcourt', 'PHC'),
        ('Kano',          'KAN'),
        ('Enugu',         'ENU'),
        ('Ibadan',        'IBA')
        ON CONFLICT (code) DO NOTHING;
    """)


def downgrade() -> None:
    for table in [
        'audit_logs', 'notifications', 'staff_onboarding_requests',
        'outage_incidents', 'projects', 'task_tags', 'task_comments', 'tasks',
        'user_role_history', 'user_scopes', 'staff_profiles', 'users',
        'teams', 'departments', 'regions', 'roles'
    ]:
        op.drop_table(table)
