"""
OPSYN TASK ENGINE CORRECTIONS — MIGRATION 0034
Sprint 2 Stage 1 — S2.1.1

Adds to the tasks table:
  block_reason         TEXT            — reason when a task is blocked
  ticket_number        VARCHAR(20)     — per-tenant TSK-YYYY-NNNN identifier
  estimated_hours      FLOAT           — time estimate in hours
  form_submission_id   UUID            — FK to form_submissions (Sprint 3, nullable FK added now)

Constraints:
  UNIQUE(tenant_id, ticket_number)     — per-tenant uniqueness (not global)

Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0034'
down_revision = '0033'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── Add new columns to tasks ──────────────────────────────
    op.add_column('tasks', sa.Column('block_reason',       sa.Text(),        nullable=True))
    op.add_column('tasks', sa.Column('ticket_number',      sa.String(20),    nullable=True))
    op.add_column('tasks', sa.Column('estimated_hours',    sa.Float(),       nullable=True))
    op.add_column('tasks', sa.Column('form_submission_id', postgresql.UUID(as_uuid=True), nullable=True))

    # ── Per-tenant unique constraint on ticket_number ─────────
    # ticket_number UNIQUE per tenant — two tenants can each have TSK-2026-0001
    op.create_unique_constraint(
        'uq_tasks_tenant_ticket_number',
        'tasks',
        ['tenant_id', 'ticket_number'],
    )

    # ── Index for fast ticket lookups ─────────────────────────
    op.create_index('ix_tasks_ticket_number', 'tasks', ['ticket_number'])


def downgrade() -> None:
    op.drop_index('ix_tasks_ticket_number',  table_name='tasks')
    op.drop_constraint('uq_tasks_tenant_ticket_number', 'tasks', type_='unique')
    op.drop_column('tasks', 'form_submission_id')
    op.drop_column('tasks', 'estimated_hours')
    op.drop_column('tasks', 'ticket_number')
    op.drop_column('tasks', 'block_reason')
