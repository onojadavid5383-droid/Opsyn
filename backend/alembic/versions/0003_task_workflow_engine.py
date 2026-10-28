"""
OPSYN TASK WORKFLOW ENGINE MIGRATION
Revision: 0003

Upgrades the task module from simple CRUD to a deterministic workflow engine:

Tasks table:
  + previous_state      VARCHAR(20)             — state before last transition
  + state_changed_at    TIMESTAMPTZ             — when last transition occurred
  + responsible_user_id UUID FK users.id        — accountability owner
  + pipeline_id         UUID                    — logical pipeline reference
  + stage_id            UUID                    — logical stage reference

task_comments table:
  + type                VARCHAR(20) NOT NULL DEFAULT 'NORMAL'
  + mentions            JSONB       NOT NULL DEFAULT '[]'
  + parent_id           UUID FK task_comments.id  — threading
  + approval_action     VARCHAR(20) nullable       — approved | rejected | pending
  + is_resolved         BOOLEAN     NOT NULL DEFAULT false
  + updated_at          TIMESTAMPTZ DEFAULT now()

New tables:
  task_dependencies     — enforces blocking dependency relationships
  task_audit_entries    — immutable per-task transition log

Data migration:
  backlog   → new      (old bucket-based state aligned to new workflow)
  in_review → review   (renamed for clarity)

Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0003'
down_revision = '0002'
branch_labels = None
depends_on    = None


def upgrade() -> None:

    # ── tasks — new workflow tracking columns ─────────────────
    op.add_column('tasks', sa.Column(
        'previous_state', sa.String(20), nullable=True,
    ))
    op.add_column('tasks', sa.Column(
        'state_changed_at', sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column('tasks', sa.Column(
        'responsible_user_id',
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    ))
    op.add_column('tasks', sa.Column(
        'pipeline_id', postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.add_column('tasks', sa.Column(
        'stage_id', postgresql.UUID(as_uuid=True), nullable=True,
    ))

    # ── task_comments — allow NULL author for SYSTEM comments ──
    op.alter_column('task_comments', 'author_user_id', nullable=True)

    # ── task_comments — typed, threaded, workflow-aware ───────
    op.add_column('task_comments', sa.Column(
        'type', sa.String(20), nullable=False, server_default='NORMAL',
    ))
    op.add_column('task_comments', sa.Column(
        'mentions', postgresql.JSONB(), nullable=False, server_default='[]',
    ))
    op.add_column('task_comments', sa.Column(
        'parent_id',
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey('task_comments.id', ondelete='SET NULL'),
        nullable=True,
    ))
    op.add_column('task_comments', sa.Column(
        'approval_action', sa.String(20), nullable=True,
    ))
    op.add_column('task_comments', sa.Column(
        'is_resolved', sa.Boolean(), nullable=False, server_default='false',
    ))
    op.add_column('task_comments', sa.Column(
        'updated_at', sa.DateTime(timezone=True),
        nullable=True, server_default=sa.text('now()'),
    ))

    # ── task_dependencies — blocking dependency graph ─────────
    op.create_table(
        'task_dependencies',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True),
            primary_key=True, server_default=sa.text('gen_random_uuid()'),
        ),
        sa.Column(
            'task_id', postgresql.UUID(as_uuid=True),
            sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column(
            'depends_on_task_id', postgresql.UUID(as_uuid=True),
            sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
        ),
        sa.UniqueConstraint('task_id', 'depends_on_task_id', name='uq_task_dependency'),
    )
    op.create_index('ix_task_dependencies_task_id', 'task_dependencies', ['task_id'])

    # ── task_audit_entries — immutable per-task transition log ─
    op.create_table(
        'task_audit_entries',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True),
            primary_key=True, server_default=sa.text('gen_random_uuid()'),
        ),
        sa.Column(
            'task_id', postgresql.UUID(as_uuid=True),
            sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column(
            'actor_id', postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True,
        ),
        sa.Column('from_state',   sa.String(20), nullable=True),
        sa.Column('to_state',     sa.String(20), nullable=True),
        sa.Column(
            'trigger_type', sa.String(20), nullable=False, server_default='manual',
        ),
        sa.Column('comment_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('note',       sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
        ),
    )
    op.create_index('ix_task_audit_entries_task_id', 'task_audit_entries', ['task_id'])
    op.create_index('ix_task_audit_entries_created_at', 'task_audit_entries', ['created_at'])

    # ── Data migration: align existing status values ──────────
    # backlog   → new      (was a bucket concept, now a proper first state)
    # in_review → review   (renamed for naming consistency with state machine)
    op.execute("UPDATE tasks SET status = 'new'    WHERE status = 'backlog'")
    op.execute("UPDATE tasks SET status = 'review' WHERE status = 'in_review'")

    # Back-fill state_changed_at from updated_at for existing rows
    op.execute("UPDATE tasks SET state_changed_at = updated_at WHERE state_changed_at IS NULL")


def downgrade() -> None:
    # Reverse data migration
    op.execute("UPDATE tasks SET status = 'in_review' WHERE status = 'review'")
    op.execute("UPDATE tasks SET status = 'backlog'   WHERE status = 'new'")

    # Drop new tables
    op.drop_index('ix_task_audit_entries_created_at', table_name='task_audit_entries')
    op.drop_index('ix_task_audit_entries_task_id',    table_name='task_audit_entries')
    op.drop_table('task_audit_entries')

    op.drop_index('ix_task_dependencies_task_id', table_name='task_dependencies')
    op.drop_table('task_dependencies')

    # Restore author_user_id NOT NULL
    op.alter_column('task_comments', 'author_user_id', nullable=False)

    # Drop new task_comments columns
    op.drop_column('task_comments', 'updated_at')
    op.drop_column('task_comments', 'is_resolved')
    op.drop_column('task_comments', 'approval_action')
    op.drop_column('task_comments', 'parent_id')
    op.drop_column('task_comments', 'mentions')
    op.drop_column('task_comments', 'type')

    # Drop new tasks columns
    op.drop_column('tasks', 'stage_id')
    op.drop_column('tasks', 'pipeline_id')
    op.drop_column('tasks', 'responsible_user_id')
    op.drop_column('tasks', 'state_changed_at')
    op.drop_column('tasks', 'previous_state')
