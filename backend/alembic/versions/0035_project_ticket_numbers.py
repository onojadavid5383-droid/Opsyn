"""
OPSYN PROJECT TICKET NUMBERS — MIGRATION 0035
Sprint 2 Stage 2 — S2.2.1

Adds to the projects table:
  ticket_number  VARCHAR(20)  — per-tenant PRJ-YYYY-NNNN identifier

Constraints:
  UNIQUE(tenant_id, ticket_number)  — per-tenant uniqueness

Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa

revision      = '0035'
down_revision = '0034'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('ticket_number', sa.String(20), nullable=True))

    op.create_unique_constraint(
        'uq_projects_tenant_ticket_number',
        'projects',
        ['tenant_id', 'ticket_number'],
    )

    op.create_index('ix_projects_ticket_number', 'projects', ['ticket_number'])


def downgrade() -> None:
    op.drop_index('ix_projects_ticket_number', table_name='projects')
    op.drop_constraint('uq_projects_tenant_ticket_number', 'projects', type_='unique')
    op.drop_column('projects', 'ticket_number')
