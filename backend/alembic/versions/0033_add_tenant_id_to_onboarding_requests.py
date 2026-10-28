"""
Add tenant_id to staff_onboarding_requests

staff_onboarding_requests was omitted from migration 0028 which added
tenant_id to all other tables. This migration adds the column and backfills
existing rows with the dev tenant UUID, matching the pattern from 0028.

Revision: 0033
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0033'
down_revision = '0032'
branch_labels = None
depends_on    = None

DEV_TENANT_UUID = '00000000-0000-0000-0000-000000000001'


def upgrade() -> None:
    op.add_column(
        'staff_onboarding_requests',
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        f"UPDATE staff_onboarding_requests SET tenant_id = '{DEV_TENANT_UUID}' WHERE tenant_id IS NULL"
    )
    op.alter_column('staff_onboarding_requests', 'tenant_id', nullable=False)
    op.create_foreign_key(
        'fk_staff_onboarding_requests_tenant_id',
        'staff_onboarding_requests', 'tenants',
        ['tenant_id'], ['id'],
        ondelete='CASCADE',
    )
    op.create_index('ix_staff_onboarding_requests_tenant_id', 'staff_onboarding_requests', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_staff_onboarding_requests_tenant_id', table_name='staff_onboarding_requests')
    op.drop_constraint('fk_staff_onboarding_requests_tenant_id', 'staff_onboarding_requests', type_='foreignkey')
    op.drop_column('staff_onboarding_requests', 'tenant_id')
