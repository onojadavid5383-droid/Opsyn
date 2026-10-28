"""task reopened flag — adds is_reopened boolean to tasks table

Revision ID: 0051
Revises: 0050
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa

revision = '0051'
down_revision = '0050'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column(
        'is_reopened', sa.Boolean(), nullable=False, server_default='false'
    ))
    op.create_index('idx_tasks_is_reopened', 'tasks', ['is_reopened', 'tenant_id'])


def downgrade() -> None:
    op.drop_index('idx_tasks_is_reopened', table_name='tasks')
    op.drop_column('tasks', 'is_reopened')
