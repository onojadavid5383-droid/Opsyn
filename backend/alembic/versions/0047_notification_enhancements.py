"""notification enhancements — structured categories + related entity links

Revision ID: 0047
Revises: 0046
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0047'
down_revision = '0046'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('notifications', sa.Column(
        'notification_category', sa.String(30), nullable=True, server_default='general'
    ))
    op.add_column('notifications', sa.Column('related_task_id', UUID(as_uuid=True), nullable=True))
    op.add_column('notifications', sa.Column('related_project_id', UUID(as_uuid=True), nullable=True))
    op.add_column('notifications', sa.Column('related_dept_id', UUID(as_uuid=True), nullable=True))
    op.add_column('notifications', sa.Column('sender_id', UUID(as_uuid=True), nullable=True))

    op.create_foreign_key('fk_notif_task', 'notifications', 'tasks', ['related_task_id'], ['id'])
    op.create_foreign_key('fk_notif_project', 'notifications', 'projects', ['related_project_id'], ['id'])
    op.create_foreign_key('fk_notif_dept', 'notifications', 'departments', ['related_dept_id'], ['id'])
    op.create_foreign_key('fk_notif_sender', 'notifications', 'users', ['sender_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_notif_sender', 'notifications', type_='foreignkey')
    op.drop_constraint('fk_notif_dept', 'notifications', type_='foreignkey')
    op.drop_constraint('fk_notif_project', 'notifications', type_='foreignkey')
    op.drop_constraint('fk_notif_task', 'notifications', type_='foreignkey')
    op.drop_column('notifications', 'sender_id')
    op.drop_column('notifications', 'related_dept_id')
    op.drop_column('notifications', 'related_project_id')
    op.drop_column('notifications', 'related_task_id')
    op.drop_column('notifications', 'notification_category')
