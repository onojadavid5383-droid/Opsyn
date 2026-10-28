"""
OPSYN PROJECT CLASSIFICATION MIGRATION
Revision: 0002
Adds project_type and owner_id to the projects table.
Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('project_type', sa.String(20), nullable=False, server_default='internal'))
    op.add_column('projects', sa.Column('owner_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'owner_id')
    op.drop_column('projects', 'project_type')
