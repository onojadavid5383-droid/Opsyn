"""
OPSYN PROJECT STAGE COMMENTS MIGRATION
Revision: 0023

Adds project_stage_comments table for tracking comments on pipeline stages.

project_stage_comments table:
  + id                  UUID PRIMARY KEY DEFAULT gen_random_uuid()
  + project_id          UUID FK projects.id NOT NULL
  + stage_id            UUID FK project_pipeline_stages.id NOT NULL
  + author_user_id      UUID FK users.id NOT NULL
  + body                TEXT NOT NULL
  + comment_type        VARCHAR(30) DEFAULT 'progress'
  + attachments         JSONB NULLABLE
  + created_at          TIMESTAMPTZ DEFAULT now()

Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0023'
down_revision = '0022'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table('project_stage_comments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('stage_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('author_user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('comment_type', sa.String(30), nullable=False, server_default=sa.text("'progress'")),
        sa.Column('attachments', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    op.create_foreign_key(
        'fk_project_stage_comments_project_id',
        'project_stage_comments', 'projects',
        ['project_id'], ['id'],
        ondelete='CASCADE'
    )

    # FK to project_pipeline_stages is added in migration 0024 after that table is created

    op.create_foreign_key(
        'fk_project_stage_comments_author_user_id',
        'project_stage_comments', 'users',
        ['author_user_id'], ['id'],
        ondelete='CASCADE'
    )


def downgrade() -> None:
    op.drop_table('project_stage_comments')