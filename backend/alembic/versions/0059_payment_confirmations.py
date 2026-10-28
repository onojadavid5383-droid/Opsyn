"""Customer Module Phase 1 — create payment_confirmations

Written by the Finance App webhook handler when payment is confirmed.
confirmation_payload stores the raw webhook body for audit/replay.

Revision ID: 0059
Revises: 0058
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0059'
down_revision = '0058'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'payment_confirmations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('payment_request_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('payment_requests.id', ondelete='CASCADE'), nullable=False),
        # Name of the external app that confirmed payment (e.g. 'finance_app')
        sa.Column('confirmed_by_app', sa.String(100), nullable=False),
        # Raw webhook payload stored for audit and replay
        sa.Column('confirmation_payload', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default='{}'),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    op.create_index(
        'ix_payment_confirmations_request',
        'payment_confirmations',
        ['payment_request_id'],
    )
    # GIN index for JSONB payload queries
    op.create_index(
        'ix_payment_confirmations_payload_gin',
        'payment_confirmations',
        ['confirmation_payload'],
        postgresql_using='gin',
    )


def downgrade() -> None:
    op.drop_index('ix_payment_confirmations_payload_gin', table_name='payment_confirmations')
    op.drop_index('ix_payment_confirmations_request', table_name='payment_confirmations')
    op.drop_table('payment_confirmations')
