"""add is_deleted to users

Revision ID: 0075
Revises: 0074
Create Date: 2026-05-18

"""
from alembic import op
import sqlalchemy as sa

revision = '0075'
down_revision = '0074'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('users', 'is_deleted')
