"""Infrastructure Management — Phase 1 (1/8): infrastructure_upload_sessions

Tracks every upload attempt (successful or not) for all FTTH asset types.
Analogous to external_task_logs in the existing system.

Revision ID: 0067
Revises: 0066
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0067'
down_revision = '0066'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # Enable PostGIS extension (idempotent — safe to run multiple times)
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        'infrastructure_upload_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        # 'splitter' | 'cabinet' | 'olt' | 'cable_route'
        sa.Column('asset_type', sa.String(30), nullable=False),
        # pending | validating | validated | approved | committing | committed | failed | rolled_back
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('original_filename', sa.String(500), nullable=True),
        # SHA-256 of the uploaded file bytes — used to detect re-uploads
        sa.Column('file_hash', sa.String(64), nullable=True),
        sa.Column('total_rows', sa.Integer(), nullable=True),
        sa.Column('valid_rows', sa.Integer(), nullable=True),
        sa.Column('duplicate_rows', sa.Integer(), nullable=True),
        sa.Column('error_rows', sa.Integer(), nullable=True),
        sa.Column('committed_rows', sa.Integer(), nullable=True),
        # Array of {row, field, error} objects
        sa.Column('validation_errors', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('submitted_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('submitted_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('approved_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('committed_at', sa.TIMESTAMP(timezone=True), nullable=True),
    )

    op.create_index('ix_infra_upload_sessions_tenant',
                    'infrastructure_upload_sessions', ['tenant_id'])
    op.create_index('ix_infra_upload_sessions_status',
                    'infrastructure_upload_sessions', ['status'])
    op.create_index('ix_infra_upload_sessions_asset_type',
                    'infrastructure_upload_sessions', ['asset_type'])
    # GIN index on JSONB validation_errors for fast filtering
    op.create_index('ix_infra_upload_sessions_errors_gin',
                    'infrastructure_upload_sessions', ['validation_errors'],
                    postgresql_using='gin')


def downgrade() -> None:
    op.drop_index('ix_infra_upload_sessions_errors_gin',
                  table_name='infrastructure_upload_sessions')
    op.drop_index('ix_infra_upload_sessions_asset_type',
                  table_name='infrastructure_upload_sessions')
    op.drop_index('ix_infra_upload_sessions_status',
                  table_name='infrastructure_upload_sessions')
    op.drop_index('ix_infra_upload_sessions_tenant',
                  table_name='infrastructure_upload_sessions')
    op.drop_table('infrastructure_upload_sessions')
