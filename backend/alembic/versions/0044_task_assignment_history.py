"""task assignment history — task_assignment_logs table

Revision ID: 0044
Revises: 0043
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0044'
down_revision = '0043'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'task_assignment_logs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('task_id', UUID(as_uuid=True), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('assigned_by', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('assigned_to', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('from_dept_id', UUID(as_uuid=True), sa.ForeignKey('departments.id'), nullable=True),
        sa.Column('to_dept_id', UUID(as_uuid=True), sa.ForeignKey('departments.id'), nullable=True),
        sa.Column('assignment_type', sa.String(30), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )
    op.create_index('idx_tal_task_id', 'task_assignment_logs', ['task_id'])

    op.execute("ALTER TABLE task_assignment_logs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY task_asgn_tenant ON task_assignment_logs "
        "USING (tenant_id::text = current_setting('app.tenant_id', TRUE))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS task_asgn_tenant ON task_assignment_logs")
    op.drop_index('idx_tal_task_id', table_name='task_assignment_logs')
    op.drop_table('task_assignment_logs')
