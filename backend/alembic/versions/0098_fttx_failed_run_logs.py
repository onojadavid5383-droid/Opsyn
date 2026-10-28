"""Persist pipeline logs directly on failed FTTx runs.

Completed runs keep their log with the output row. Failed runs have no output
row, so they need a log field on the run record for the existing log endpoint.
"""

from alembic import op
import sqlalchemy as sa

revision = "0098"
down_revision = "0097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fttx_design_runs", sa.Column("log_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("fttx_design_runs", "log_text")
