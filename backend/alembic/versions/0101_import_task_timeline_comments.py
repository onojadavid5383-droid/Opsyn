"""Import legacy task timeline comments into the task comment threads.

Revision ID: 0101
Revises: 0100
"""

from alembic import op
import sqlalchemy as sa

revision = "0101"
down_revision = "0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Task comments created by the workflow already carry their task_comment id
    # in meta.comment_id. Only standalone timeline comments need importing.
    op.execute(sa.text("""
        INSERT INTO task_comments
            (id, task_id, author_user_id, body, type, mentions, parent_id,
             approval_action, is_resolved, created_at, updated_at)
        SELECT
            timeline.id,
            timeline.entity_id,
            timeline.actor_id,
            COALESCE(timeline.body, ''),
            'NORMAL',
            '[]'::jsonb,
            NULL,
            NULL,
            FALSE,
            timeline.created_at,
            timeline.created_at
        FROM activity_timeline AS timeline
        JOIN tasks ON tasks.id = timeline.entity_id AND tasks.tenant_id = timeline.tenant_id
        WHERE timeline.entity_type = 'task'
          AND timeline.event_type = 'comment'
          AND COALESCE(timeline.meta, '{}'::jsonb) ->> 'comment_id' IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM task_comments AS comment WHERE comment.id = timeline.id
          )
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        DELETE FROM task_comments AS comment
        USING activity_timeline AS timeline
        WHERE comment.id = timeline.id
          AND timeline.entity_type = 'task'
          AND timeline.event_type = 'comment'
          AND COALESCE(timeline.meta, '{}'::jsonb) ->> 'comment_id' IS NULL
    """))
