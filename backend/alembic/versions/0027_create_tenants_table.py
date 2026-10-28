"""
OPSYN MULTI-TENANT ISOLATION — CREATE TENANTS TABLE
Revision: 0027

Creates the tenants table as the root entity for multi-tenant SaaS isolation.
Every subsequent table will FK to this table via tenant_id.

Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0027'
down_revision = '0026'
branch_labels = None
depends_on    = None

# Development tenant UUID — used to backfill all existing rows
DEV_TENANT_UUID = '00000000-0000-0000-0000-000000000001'


def upgrade() -> None:
    # ── tenants ──────────────────────────────────────────────────
    op.create_table(
        'tenants',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text('gen_random_uuid()'),
        ),
        sa.Column('name',       sa.String(200), nullable=False),
        sa.Column('slug',       sa.String(80),  nullable=False),
        sa.Column('plan',       sa.String(20),  nullable=False, server_default='starter'),
        sa.Column('max_users',  sa.Integer(),   nullable=False, server_default='50'),
        sa.Column('is_active',  sa.Boolean(),   nullable=False, server_default='true'),
        sa.Column('settings',   postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index('ix_tenants_slug', 'tenants', ['slug'], unique=True)

    # Insert the development tenant used to backfill all existing rows
    op.execute(f"""
        INSERT INTO tenants (id, name, slug, plan, max_users, is_active, settings)
        VALUES (
            '{DEV_TENANT_UUID}',
            'Development Tenant',
            'dev',
            'enterprise',
            9999,
            true,
            '{{}}'
        )
        ON CONFLICT (id) DO NOTHING;
    """)


def downgrade() -> None:
    op.drop_index('ix_tenants_slug', table_name='tenants')
    op.drop_table('tenants')
