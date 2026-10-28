"""Customer Module Phase 1 — create customer_form_submissions

One row per form submission per customer per pipeline stage. Stores the
complete submitted_data snapshot so historical schema versions can always
be replayed. The form_schema_id references the version active at submit time.

Revision ID: 0057
Revises: 0056
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0057'
down_revision = '0056'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'customer_form_submissions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('customers.id', ondelete='CASCADE'), nullable=False),
        # References the exact schema version submitted against
        sa.Column('form_schema_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('form_schemas.id', ondelete='RESTRICT'), nullable=False),
        # Full snapshot of submitted field values
        sa.Column('submitted_data', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default='{}'),
        sa.Column('submitted_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        # Pipeline stage order at which this submission was made
        sa.Column('stage', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    op.create_index(
        'ix_cfs_customer',
        'customer_form_submissions',
        ['customer_id'],
    )
    op.create_index(
        'ix_cfs_tenant_stage',
        'customer_form_submissions',
        ['tenant_id', 'stage'],
    )
    # GIN index on submitted_data for JSONB queries
    op.create_index(
        'ix_cfs_submitted_data_gin',
        'customer_form_submissions',
        ['submitted_data'],
        postgresql_using='gin',
    )


def downgrade() -> None:
    op.drop_index('ix_cfs_submitted_data_gin', table_name='customer_form_submissions')
    op.drop_index('ix_cfs_tenant_stage', table_name='customer_form_submissions')
    op.drop_index('ix_cfs_customer', table_name='customer_form_submissions')
    op.drop_table('customer_form_submissions')
