"""archive reference — FTS index + archive_references table

Revision ID: 0049
Revises: 0048
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0049'
down_revision = '0048'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX idx_tasks_archive_fts ON tasks "
        "USING gin(to_tsvector('english', title || ' ' || coalesce(description, ''))) "
        "WHERE pipeline_stage = 'archive' AND is_deleted = FALSE"
    )

    op.create_table(
        'archive_references',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('task_id', UUID(as_uuid=True), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column(
            'referenced_archive_task_id', UUID(as_uuid=True),
            sa.ForeignKey('tasks.id', ondelete='SET NULL'), nullable=True,
        ),
        sa.Column(
            'referenced_archive_project_id', UUID(as_uuid=True),
            sa.ForeignKey('projects.id', ondelete='SET NULL'), nullable=True,
        ),
        sa.Column('referenced_by', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )


def downgrade() -> None:
    op.drop_table('archive_references')
    op.execute("DROP INDEX IF EXISTS idx_tasks_archive_fts")
