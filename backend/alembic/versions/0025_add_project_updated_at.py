"""
OPSYN ADD PROJECT UPDATED_AT COLUMN
Revision: 0025
Adds updated_at to the projects table.
Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'projects',
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
    )


def downgrade() -> None:
    op.drop_column('projects', 'updated_at')
