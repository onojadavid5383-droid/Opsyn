"""task workflow engine — task_scope, soft delete, dual approval, pipeline_stage

Revision ID: 0043
Revises: 0042
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0043'
down_revision = '0042'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('task_scope', sa.String(20), nullable=False, server_default='internal'))
    op.add_column('tasks', sa.Column('pipeline_stage', sa.String(30), nullable=False, server_default='backlog'))
    op.add_column('tasks', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tasks', sa.Column('deleted_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('tasks', sa.Column('deleted_by', UUID(as_uuid=True), nullable=True))
    op.add_column('tasks', sa.Column('deletion_reason', sa.Text(), nullable=True))
    op.add_column('tasks', sa.Column('assignee_confirmed_done', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tasks', sa.Column('creator_approved_done', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tasks', sa.Column('assignee_done_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('tasks', sa.Column('creator_approved_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('tasks', sa.Column('source_app', sa.String(50), nullable=True))

    op.create_foreign_key(
        'fk_tasks_deleted_by_users', 'tasks', 'users', ['deleted_by'], ['id']
    )

    op.create_index('idx_tasks_task_scope', 'tasks', ['task_scope', 'tenant_id'])
    op.create_index('idx_tasks_is_deleted', 'tasks', ['is_deleted', 'tenant_id'])
    op.create_index('idx_tasks_pipeline_stage', 'tasks', ['pipeline_stage', 'tenant_id'])


def downgrade() -> None:
    op.drop_index('idx_tasks_pipeline_stage', table_name='tasks')
    op.drop_index('idx_tasks_is_deleted', table_name='tasks')
    op.drop_index('idx_tasks_task_scope', table_name='tasks')
    op.drop_constraint('fk_tasks_deleted_by_users', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'source_app')
    op.drop_column('tasks', 'creator_approved_at')
    op.drop_column('tasks', 'assignee_done_at')
    op.drop_column('tasks', 'creator_approved_done')
    op.drop_column('tasks', 'assignee_confirmed_done')
    op.drop_column('tasks', 'deletion_reason')
    op.drop_column('tasks', 'deleted_by')
    op.drop_column('tasks', 'deleted_at')
    op.drop_column('tasks', 'is_deleted')
    op.drop_column('tasks', 'pipeline_stage')
    op.drop_column('tasks', 'task_scope')
