"""Customer Module Phase 1 — create payment_requests

Auto-generated on customer creation. Tracks payment link, amount, status and
expiry. Status transitions: pending → paid | expired | refunded.

Revision ID: 0058
Revises: 0057
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0058'
down_revision = '0057'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'payment_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('customers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False,
                  server_default='0.00'),
        sa.Column('currency', sa.String(10), nullable=False, server_default='NGN'),
        sa.Column('payment_link', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        # Provider reference for reconciliation
        sa.Column('provider_reference', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    # Composite index for tenant + status queries (billing dashboards)
    op.create_index('ix_payment_requests_tenant_status', 'payment_requests',
                    ['tenant_id', 'status'])
    op.create_index('ix_payment_requests_customer', 'payment_requests', ['customer_id'])


def downgrade() -> None:
    op.drop_index('ix_payment_requests_customer', table_name='payment_requests')
    op.drop_index('ix_payment_requests_tenant_status', table_name='payment_requests')
    op.drop_table('payment_requests')
