"""Infrastructure Management — Phase 1 (2/8): infrastructure_deletion_sessions

Tracks every batch deletion attempt for all FTTH asset types.
Two-phase: validate → preview → approve → execute.

Revision ID: 0068
Revises: 0067
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0068'
down_revision = '0067'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        'infrastructure_deletion_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        # 'splitter' | 'cabinet' | 'olt' | 'cable_route'
        sa.Column('asset_type', sa.String(30), nullable=False),
        # pending | validated | approved | executed | failed
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('original_filename', sa.String(500), nullable=True),
        sa.Column('total_rows', sa.Integer(), nullable=True),
        sa.Column('matched_rows', sa.Integer(), nullable=True),
        sa.Column('unmatched_rows', sa.Integer(), nullable=True),
        sa.Column('deleted_rows', sa.Integer(), nullable=True),
        # Array of {key, status:'matched'|'unmatched'} objects
        sa.Column('match_details', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('submitted_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('submitted_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('approved_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('executed_at', sa.TIMESTAMP(timezone=True), nullable=True),
    )

    op.create_index('ix_infra_deletion_sessions_tenant',
                    'infrastructure_deletion_sessions', ['tenant_id'])
    op.create_index('ix_infra_deletion_sessions_status',
                    'infrastructure_deletion_sessions', ['status'])
    op.create_index('ix_infra_deletion_sessions_match_details_gin',
                    'infrastructure_deletion_sessions', ['match_details'],
                    postgresql_using='gin')


def downgrade() -> None:
    op.drop_index('ix_infra_deletion_sessions_match_details_gin',
                  table_name='infrastructure_deletion_sessions')
    op.drop_index('ix_infra_deletion_sessions_status',
                  table_name='infrastructure_deletion_sessions')
    op.drop_index('ix_infra_deletion_sessions_tenant',
                  table_name='infrastructure_deletion_sessions')
    op.drop_table('infrastructure_deletion_sessions')
