"""task approval records — task_completion_approvals table

Revision ID: 0048
Revises: 0047
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0048'
down_revision = '0047'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'task_completion_approvals',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('task_id', UUID(as_uuid=True), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('approval_type', sa.String(20), nullable=False),
        sa.Column('actor_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )
    op.create_index('idx_tca_task_id', 'task_completion_approvals', ['task_id'])


def downgrade() -> None:
    op.drop_index('idx_tca_task_id', table_name='task_completion_approvals')
    op.drop_table('task_completion_approvals')
