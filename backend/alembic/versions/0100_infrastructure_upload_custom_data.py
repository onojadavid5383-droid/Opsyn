"""Store schema-defined infrastructure upload fields on assets.

Revision ID: 0100
Revises: 0099
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0100"
down_revision = "0099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("splitter_boxes", "cabinets", "olts"):
        op.add_column(table, sa.Column("custom_data", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
        op.alter_column(table, "custom_data", server_default=None)


def downgrade() -> None:
    for table in ("olts", "cabinets", "splitter_boxes"):
        op.drop_column(table, "custom_data")
