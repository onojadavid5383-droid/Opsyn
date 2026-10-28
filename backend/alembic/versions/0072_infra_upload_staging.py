"""Infrastructure Management — Phase 1 (6/8): infrastructure_upload_staging

Staging rows written during validation. Moved to live tables on commit.
Deleted on rollback/rejection. Enables atomic two-phase upload.

Revision ID: 0072
Revises: 0071
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0072'
down_revision = '0071'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        'infrastructure_upload_staging',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('session_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('infrastructure_upload_sessions.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        # 'splitter' | 'cabinet' | 'olt' | 'cable_route'
        sa.Column('asset_type', sa.String(30), nullable=False),
        # Original Excel row number (1-based, after header)
        sa.Column('row_number', sa.Integer(), nullable=False),
        # Parsed row values as key-value map
        sa.Column('row_data', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('is_valid', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_duplicate', sa.Boolean(), nullable=False, server_default='false'),
        # Field-level errors: [{field, error}]
        sa.Column('errors', postgresql.JSONB(), nullable=True, server_default='[]'),
        # Set to TRUE when this row has been moved to the live table
        sa.Column('committed', sa.Boolean(), nullable=False, server_default='false'),
    )

    op.create_index('ix_infra_staging_session',
                    'infrastructure_upload_staging', ['session_id'])
    op.create_index('ix_infra_staging_tenant',
                    'infrastructure_upload_staging', ['tenant_id'])
    op.create_index('ix_infra_staging_valid',
                    'infrastructure_upload_staging', ['session_id', 'is_valid', 'committed'])
    op.create_index('ix_infra_staging_row_data_gin',
                    'infrastructure_upload_staging', ['row_data'],
                    postgresql_using='gin')


def downgrade() -> None:
    op.drop_index('ix_infra_staging_row_data_gin',
                  table_name='infrastructure_upload_staging')
    op.drop_index('ix_infra_staging_valid',
                  table_name='infrastructure_upload_staging')
    op.drop_index('ix_infra_staging_tenant',
                  table_name='infrastructure_upload_staging')
    op.drop_index('ix_infra_staging_session',
                  table_name='infrastructure_upload_staging')
    op.drop_table('infrastructure_upload_staging')
