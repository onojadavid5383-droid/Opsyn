"""Customer Module Phase 1 — create customers table

Master customer record. source_app tracks which external application originated
the record. Supports soft-delete via is_deleted flag.

Status lifecycle: pending → active → suspended | churned

Revision ID: 0055
Revises: 0054
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0055'
down_revision = '0054'
branch_labels = None
depends_on = None

VALID_STATUSES = ('pending', 'active', 'suspended', 'churned')
VALID_SOURCE_APPS = ('field_tech', 'hr', 'sales', 'coverage_checker', 'manual')


def upgrade() -> None:
    op.create_table(
        'customers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),

        # Identity
        sa.Column('first_name', sa.String(100), nullable=False),
        sa.Column('last_name', sa.String(100), nullable=False),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('phone', sa.String(50), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),

        # Lifecycle
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),

        # Origin tracking
        sa.Column('source_app', sa.String(50), nullable=False, server_default='manual'),
        # external_ref_id used for idempotency when created from external webhook
        sa.Column('external_ref_id', sa.String(255), nullable=True),

        # Ownership
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('assigned_department_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('departments.id', ondelete='SET NULL'), nullable=True),

        # Soft-delete
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),

        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )

    # Composite indexes for common query patterns
    op.create_index('ix_customers_tenant_status', 'customers', ['tenant_id', 'status'])
    op.create_index('ix_customers_tenant_source', 'customers', ['tenant_id', 'source_app'])
    op.create_index('ix_customers_tenant_deleted', 'customers', ['tenant_id', 'is_deleted'])
    # Unique external_ref_id per tenant for idempotency
    op.create_unique_constraint(
        'uq_customers_tenant_external_ref',
        'customers',
        ['tenant_id', 'external_ref_id'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_customers_tenant_external_ref', 'customers', type_='unique')
    op.drop_index('ix_customers_tenant_deleted', table_name='customers')
    op.drop_index('ix_customers_tenant_source', table_name='customers')
    op.drop_index('ix_customers_tenant_status', table_name='customers')
    op.drop_table('customers')
