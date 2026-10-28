"""task rejection log — task_rejection_logs table

Revision ID: 0045
Revises: 0044
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0045'
down_revision = '0044'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'task_rejection_logs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('task_id', UUID(as_uuid=True), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('rejected_by', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('rejection_type', sa.String(30), nullable=False),
        sa.Column('from_dept_id', UUID(as_uuid=True), sa.ForeignKey('departments.id'), nullable=True),
        sa.Column('to_dept_id', UUID(as_uuid=True), sa.ForeignKey('departments.id'), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('previous_status', sa.String(30), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )
    op.create_index('idx_trl_task_id', 'task_rejection_logs', ['task_id'])

    op.execute("ALTER TABLE task_rejection_logs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY task_rej_tenant ON task_rejection_logs "
        "USING (tenant_id::text = current_setting('app.tenant_id', TRUE))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS task_rej_tenant ON task_rejection_logs")
    op.drop_index('idx_trl_task_id', table_name='task_rejection_logs')
    op.drop_table('task_rejection_logs')
