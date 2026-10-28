"""project source task — links auto-generated projects back to source external task

Revision ID: 0050
Revises: 0049
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0050'
down_revision = '0049'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('projects', sa.Column(
        'source_task_id', UUID(as_uuid=True), nullable=True
    ))
    op.add_column('projects', sa.Column('source_app', sa.String(50), nullable=True))
    op.add_column('projects', sa.Column(
        'auto_generated', sa.Boolean(), nullable=False, server_default='false'
    ))

    op.create_foreign_key(
        'fk_projects_source_task', 'projects', 'tasks', ['source_task_id'], ['id'],
        ondelete='SET NULL',
    )

    op.create_index('idx_projects_source_task', 'projects', ['source_task_id'])
    op.create_index('idx_projects_auto', 'projects', ['auto_generated', 'tenant_id'])


def downgrade() -> None:
    op.drop_index('idx_projects_auto', table_name='projects')
    op.drop_index('idx_projects_source_task', table_name='projects')
    op.drop_constraint('fk_projects_source_task', 'projects', type_='foreignkey')
    op.drop_column('projects', 'auto_generated')
    op.drop_column('projects', 'source_app')
    op.drop_column('projects', 'source_task_id')
