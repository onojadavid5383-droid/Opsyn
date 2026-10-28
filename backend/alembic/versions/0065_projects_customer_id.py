"""Customer Module Phase 3 — add customer_id to projects

Links a project back to the customer that originated it, enabling the
Customer Detail page to display the project pipeline in Phase 5.
Nullable because most existing projects are not customer-originated.

Revision ID: 0065
Revises: 0064
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0065'
down_revision = '0064'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'projects',
        sa.Column(
            'customer_id',
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        'fk_projects_customer_id',
        'projects', 'customers',
        ['customer_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_projects_customer_id',
        'projects',
        ['customer_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_projects_customer_id', table_name='projects')
    op.drop_constraint('fk_projects_customer_id', 'projects', type_='foreignkey')
    op.drop_column('projects', 'customer_id')
