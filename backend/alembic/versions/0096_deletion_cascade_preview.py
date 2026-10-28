"""
Infrastructure deletion — cascade preview columns.

Deleting a cabinet or a First-Level splitter now takes its dependants with it
(splitter_boxes.cabinet_id and parent_splitter_id are ON DELETE SET NULL, so
children would otherwise be orphaned and left live). That is correct behaviour
but it means the approved row count is no longer the spreadsheet row count, so
the approver has to be shown both before they confirm.

Adds to infrastructure_deletion_sessions:
  cascaded_rows  — how many dependants execute will remove beyond the matches
  cascade_preview — the same set as [{asset_id, asset_key, parent_key}] so the
                   confirmation screen can list them

Populated by the upload/preview endpoint, not by execute.

Revision ID: 0096
Revises: 0095
"""

from alembic import op

revision      = '0096'
down_revision = '0095'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE infrastructure_deletion_sessions
            ADD COLUMN IF NOT EXISTS cascaded_rows integer NOT NULL DEFAULT 0
    """)
    op.execute("""
        ALTER TABLE infrastructure_deletion_sessions
            ADD COLUMN IF NOT EXISTS cascade_preview jsonb NOT NULL DEFAULT '[]'::jsonb
    """)
    # asyncpg refuses more than one command per execute().
    op.execute("""
        COMMENT ON COLUMN infrastructure_deletion_sessions.cascaded_rows IS
            'Dependants execute will soft-delete beyond the matched rows'
    """)
    op.execute("""
        COMMENT ON COLUMN infrastructure_deletion_sessions.cascade_preview IS
            'Preview of those dependants: [{asset_id, asset_key, parent_key}]'
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE infrastructure_deletion_sessions
            DROP COLUMN IF EXISTS cascade_preview
    """)
    op.execute("""
        ALTER TABLE infrastructure_deletion_sessions
            DROP COLUMN IF EXISTS cascaded_rows
    """)