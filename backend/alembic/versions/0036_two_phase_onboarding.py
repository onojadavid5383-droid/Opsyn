"""
OPSYN TWO-PHASE ONBOARDING — MIGRATION 0036
Sprint 2 Stage 3 — S2.3.1

Adds to staff_onboarding_requests:
  manager_approved_by       UUID FK users.id  — manager who approved phase 1
  manager_approved_at       TIMESTAMPTZ       — when manager approved
  manager_rejection_reason  TEXT              — reason if manager rejected

Changes approval_status values:
  pending → pending_manager (first phase, awaiting line manager)
  New: pending_admin (phase 2, awaiting admin)
  approved / rejected — unchanged

Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0036'
down_revision = '0035'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.add_column(
        'staff_onboarding_requests',
        sa.Column('manager_approved_by', postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        'staff_onboarding_requests',
        sa.Column('manager_approved_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'staff_onboarding_requests',
        sa.Column('manager_rejection_reason', sa.Text(), nullable=True)
    )

    # Migrate existing 'pending' rows → 'pending_manager'
    op.execute(
        "UPDATE staff_onboarding_requests SET approval_status = 'pending_manager' "
        "WHERE approval_status = 'pending'"
    )

    op.create_foreign_key(
        'fk_onboarding_manager_approved_by',
        'staff_onboarding_requests', 'users',
        ['manager_approved_by'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_onboarding_manager_approved_by', 'staff_onboarding_requests', type_='foreignkey')
    op.execute(
        "UPDATE staff_onboarding_requests SET approval_status = 'pending' "
        "WHERE approval_status = 'pending_manager'"
    )
    op.drop_column('staff_onboarding_requests', 'manager_rejection_reason')
    op.drop_column('staff_onboarding_requests', 'manager_approved_at')
    op.drop_column('staff_onboarding_requests', 'manager_approved_by')
