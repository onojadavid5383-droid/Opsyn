"""Infrastructure Management — Phase 1 (7/8): infrastructure_audit_log

Full audit trail for every upload, deletion, and restore action on
FTTH assets. actor_label uses the three-level fallback pattern.

Revision ID: 0073
Revises: 0072
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0073'
down_revision = '0072'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        'infrastructure_audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        # 'splitter' | 'cabinet' | 'olt' | 'cable_route'
        sa.Column('asset_type', sa.String(30), nullable=False),
        # UUID of the affected live asset (nullable for session-level events)
        sa.Column('asset_id', postgresql.UUID(as_uuid=True), nullable=True),
        # Human-readable key for the asset (box_id, cabinet_id, OLT name)
        sa.Column('asset_key', sa.String(200), nullable=True),
        # 'upload' | 'delete' | 'soft_delete' | 'restore'
        sa.Column('action', sa.String(30), nullable=False),
        # Upload or deletion session ID (nullable for direct single-item actions)
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('actor_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        # Resolved display name: staff_profile.full_name → username → 'System'
        sa.Column('actor_label', sa.String(200), nullable=True),
        sa.Column('timestamp', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        # Row state snapshots (JSONB) — old_data NULL for creates
        sa.Column('old_data', postgresql.JSONB(), nullable=True),
        sa.Column('new_data', postgresql.JSONB(), nullable=True),
    )

    op.create_index('ix_infra_audit_tenant_ts',
                    'infrastructure_audit_log', ['tenant_id', 'timestamp'])
    op.create_index('ix_infra_audit_asset',
                    'infrastructure_audit_log', ['asset_id'])
    op.create_index('ix_infra_audit_asset_type',
                    'infrastructure_audit_log', ['tenant_id', 'asset_type'])
    op.create_index('ix_infra_audit_session',
                    'infrastructure_audit_log', ['session_id'])


def downgrade() -> None:
    op.drop_index('ix_infra_audit_session', table_name='infrastructure_audit_log')
    op.drop_index('ix_infra_audit_asset_type', table_name='infrastructure_audit_log')
    op.drop_index('ix_infra_audit_asset', table_name='infrastructure_audit_log')
    op.drop_index('ix_infra_audit_tenant_ts', table_name='infrastructure_audit_log')
    op.drop_table('infrastructure_audit_log')
