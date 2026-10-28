"""task department routing — task_department_routing table

Revision ID: 0046
Revises: 0045
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0046'
down_revision = '0045'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'task_department_routing',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('task_id', UUID(as_uuid=True), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('department_id', UUID(as_uuid=True), sa.ForeignKey('departments.id'), nullable=False),
        sa.Column('assigned_by', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('assigned_to_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('routing_order', sa.Integer(), nullable=False),
        sa.Column('entered_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('exited_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('exit_reason', sa.String(30), nullable=True),
        sa.Column('is_current', sa.Boolean(), nullable=False, server_default='true'),
    )
    op.create_index('idx_tdr_task_id', 'task_department_routing', ['task_id'])
    op.create_index('idx_tdr_dept_id', 'task_department_routing', ['department_id', 'is_current'])


def downgrade() -> None:
    op.drop_index('idx_tdr_dept_id', table_name='task_department_routing')
    op.drop_index('idx_tdr_task_id', table_name='task_department_routing')
    op.drop_table('task_department_routing')
