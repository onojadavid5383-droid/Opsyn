"""Customer Module Phase 1 — create customer_field_values

Flat field value store. One row per field per customer, updated progressively
as the customer advances through pipeline stages. Department and user tracked
for audit purposes.

Revision ID: 0056
Revises: 0055
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0056'
down_revision = '0055'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'customer_field_values',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('customers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('field_definition_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('field_definitions.id', ondelete='CASCADE'), nullable=False),
        # TEXT to support all field types; validation is enforced at API layer
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('department_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('departments.id', ondelete='SET NULL'), nullable=True),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    # One value per customer per field (upsert pattern)
    op.create_unique_constraint(
        'uq_customer_field_values_customer_field',
        'customer_field_values',
        ['customer_id', 'field_definition_id'],
    )
    op.create_index(
        'ix_cfv_customer',
        'customer_field_values',
        ['customer_id'],
    )
    op.create_index(
        'ix_cfv_tenant_dept',
        'customer_field_values',
        ['tenant_id', 'department_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_cfv_tenant_dept', table_name='customer_field_values')
    op.drop_index('ix_cfv_customer', table_name='customer_field_values')
    op.drop_constraint(
        'uq_customer_field_values_customer_field', 'customer_field_values', type_='unique'
    )
    op.drop_table('customer_field_values')
