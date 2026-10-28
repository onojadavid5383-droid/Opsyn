"""Customer Module Phase 1 — create external_task_logs

Immutable log of every inbound external task/webhook call. Written BEFORE any
downstream processing so replay is always possible even when processing fails.
external_ref_id provides per-tenant idempotency for retrying external apps.

Status: received | processing | success | failed | replayed

Revision ID: 0062
Revises: 0061
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0062'
down_revision = '0061'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'external_task_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_app', sa.String(100), nullable=False),
        # Raw inbound payload stored verbatim for replay
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default='{}'),
        sa.Column('status', sa.String(20), nullable=False, server_default='received'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        # Unique key supplied by the external app for idempotent processing
        sa.Column('external_ref_id', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    # Per-tenant idempotency key — prevents duplicate processing on retries
    op.create_unique_constraint(
        'uq_etl_tenant_external_ref',
        'external_task_logs',
        ['tenant_id', 'external_ref_id'],
    )
    # Common query patterns
    op.create_index('ix_etl_tenant_status', 'external_task_logs', ['tenant_id', 'status'])
    op.create_index('ix_etl_source_app', 'external_task_logs', ['source_app'])
    # GIN index on JSONB payload for admin replay queries
    op.create_index(
        'ix_etl_payload_gin',
        'external_task_logs',
        ['payload'],
        postgresql_using='gin',
    )


def downgrade() -> None:
    op.drop_index('ix_etl_payload_gin', table_name='external_task_logs')
    op.drop_index('ix_etl_source_app', table_name='external_task_logs')
    op.drop_index('ix_etl_tenant_status', table_name='external_task_logs')
    op.drop_constraint('uq_etl_tenant_external_ref', 'external_task_logs', type_='unique')
    op.drop_table('external_task_logs')
