"""
OPSYN WEBHOOK RECEIVER — MIGRATION 0038
Sprint 3 Stage 3 — S3.3

Creates:
  webhook_api_keys — per-tenant HMAC-SHA256 secret keys for
                     external app integrations (HR, Finance, Sales,
                     Field Tech, Coverage).

RLS: tenant_isolation policy.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0038'
down_revision = '0037'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        'webhook_api_keys',
        sa.Column('id',         postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id',  postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('app_name',   sa.String(100), nullable=False),
        sa.Column('secret_key', sa.String(255), nullable=False),
        sa.Column('is_active',  sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_webhook_api_keys_tenant_app',
                    'webhook_api_keys', ['tenant_id', 'app_name'])

    op.execute("ALTER TABLE webhook_api_keys ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON webhook_api_keys
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON webhook_api_keys")
    op.drop_index('ix_webhook_api_keys_tenant_app', table_name='webhook_api_keys')
    op.drop_table('webhook_api_keys')
