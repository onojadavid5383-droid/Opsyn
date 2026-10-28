"""
OPSYN PIPELINE TEMPLATES MIGRATION
Revision: 0021

Adds pipeline_templates table for defining reusable project pipeline templates.

pipeline_templates table:
  + id                  UUID PRIMARY KEY DEFAULT gen_random_uuid()
  + name                VARCHAR(200) NOT NULL
  + description         TEXT NULLABLE
  + is_active           BOOLEAN DEFAULT TRUE
  + created_by          UUID FK users.id
  + created_at          TIMESTAMPTZ DEFAULT now()
  + updated_at          TIMESTAMPTZ

Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0021'
down_revision = '0003'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table('pipeline_templates',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    op.create_foreign_key(
        'fk_pipeline_templates_created_by',
        'pipeline_templates', 'users',
        ['created_by'], ['id'],
        ondelete='CASCADE'
    )

    # Create the shared trigger function (idempotent)
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    # Add trigger for updated_at
    op.execute("""
        CREATE TRIGGER update_pipeline_templates_updated_at
            BEFORE UPDATE ON pipeline_templates
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    op.drop_table('pipeline_templates')