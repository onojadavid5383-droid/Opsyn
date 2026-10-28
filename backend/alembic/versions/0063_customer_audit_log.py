"""Customer Module Phase 1 — create customer_audit_log

Full audit trail for every field change and lifecycle event on a customer
record. actor_id is nullable to support system-generated events.
old_value / new_value are TEXT to accommodate all field types.

Revision ID: 0063
Revises: 0062
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0063'
down_revision = '0062'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'customer_audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('customers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        # Human-readable action label (e.g. 'field_updated', 'status_changed', 'created')
        sa.Column('action', sa.String(100), nullable=False),
        # Field key or resource identifier affected
        sa.Column('field_key', sa.String(100), nullable=True),
        sa.Column('old_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    op.create_index(
        'ix_cal_customer',
        'customer_audit_log',
        ['customer_id'],
    )
    op.create_index(
        'ix_cal_tenant_created',
        'customer_audit_log',
        ['tenant_id', 'created_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_cal_tenant_created', table_name='customer_audit_log')
    op.drop_index('ix_cal_customer', table_name='customer_audit_log')
    op.drop_table('customer_audit_log')
