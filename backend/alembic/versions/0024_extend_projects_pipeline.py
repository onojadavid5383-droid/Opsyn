"""
OPSYN PROJECT PIPELINE STAGES AND EXTEND PROJECTS MIGRATION
Revision: 0024

Adds project_pipeline_stages table and extends projects table with pipeline columns.

project_pipeline_stages table:
  + id                  UUID PRIMARY KEY DEFAULT gen_random_uuid()
  + project_id          UUID FK projects.id NOT NULL
  + template_stage_id   UUID FK pipeline_template_stages.id NOT NULL
  + stage_order         INTEGER NOT NULL
  + stage_name          VARCHAR(200) NOT NULL
  + department_id       UUID FK departments.id NOT NULL
  + status              VARCHAR(30) NOT NULL DEFAULT 'pending'
  + assigned_to_user_id UUID FK users.id NULLABLE
  + entered_at          TIMESTAMPTZ NULLABLE
  + exited_at           TIMESTAMPTZ NULLABLE
  + pushed_back_reason  TEXT NULLABLE
  + pushed_back_by      UUID FK users.id NULLABLE
  + approved_by         UUID FK users.id NULLABLE
  + created_at          TIMESTAMPTZ DEFAULT now()
  + updated_at          TIMESTAMPTZ

Extends projects table:
  + pipeline_template_id    UUID FK pipeline_templates.id NULLABLE
  + current_stage_id        UUID FK project_pipeline_stages.id NULLABLE
  + pipeline_status         VARCHAR(30) DEFAULT 'not_started'
  + pipeline_started_at     TIMESTAMPTZ NULLABLE
  + pipeline_completed_at   TIMESTAMPTZ NULLABLE

Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0024'
down_revision = '0023'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # Create project_pipeline_stages table
    op.create_table('project_pipeline_stages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('template_stage_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('stage_order', sa.Integer(), nullable=False),
        sa.Column('stage_name', sa.String(200), nullable=False),
        sa.Column('department_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default=sa.text("'pending'")),
        sa.Column('assigned_to_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('entered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('exited_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('pushed_back_reason', sa.Text(), nullable=True),
        sa.Column('pushed_back_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    op.create_foreign_key(
        'fk_project_pipeline_stages_project_id',
        'project_pipeline_stages', 'projects',
        ['project_id'], ['id'],
        ondelete='CASCADE'
    )

    op.create_foreign_key(
        'fk_project_pipeline_stages_template_stage_id',
        'project_pipeline_stages', 'pipeline_template_stages',
        ['template_stage_id'], ['id'],
        ondelete='CASCADE'
    )

    op.create_foreign_key(
        'fk_project_pipeline_stages_department_id',
        'project_pipeline_stages', 'departments',
        ['department_id'], ['id'],
        ondelete='CASCADE'
    )

    op.create_foreign_key(
        'fk_project_pipeline_stages_assigned_to_user_id',
        'project_pipeline_stages', 'users',
        ['assigned_to_user_id'], ['id'],
        ondelete='SET NULL'
    )

    op.create_foreign_key(
        'fk_project_pipeline_stages_pushed_back_by',
        'project_pipeline_stages', 'users',
        ['pushed_back_by'], ['id'],
        ondelete='SET NULL'
    )

    op.create_foreign_key(
        'fk_project_pipeline_stages_approved_by',
        'project_pipeline_stages', 'users',
        ['approved_by'], ['id'],
        ondelete='SET NULL'
    )

    # FK from project_stage_comments to project_pipeline_stages (deferred from 0023)
    op.create_foreign_key(
        'fk_project_stage_comments_stage_id',
        'project_stage_comments', 'project_pipeline_stages',
        ['stage_id'], ['id'],
        ondelete='CASCADE'
    )

    # Add trigger for updated_at
    op.execute("""
        CREATE TRIGGER update_project_pipeline_stages_updated_at
            BEFORE UPDATE ON project_pipeline_stages
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    # Extend projects table
    op.add_column('projects', sa.Column(
        'pipeline_template_id', postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.add_column('projects', sa.Column(
        'current_stage_id', postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.add_column('projects', sa.Column(
        'pipeline_status', sa.String(30), nullable=False, server_default=sa.text("'not_started'"),
    ))
    op.add_column('projects', sa.Column(
        'pipeline_started_at', sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column('projects', sa.Column(
        'pipeline_completed_at', sa.DateTime(timezone=True), nullable=True,
    ))

    op.create_foreign_key(
        'fk_projects_pipeline_template_id',
        'projects', 'pipeline_templates',
        ['pipeline_template_id'], ['id'],
        ondelete='SET NULL'
    )

    op.create_foreign_key(
        'fk_projects_current_stage_id',
        'projects', 'project_pipeline_stages',
        ['current_stage_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_column('projects', 'pipeline_completed_at')
    op.drop_column('projects', 'pipeline_started_at')
    op.drop_column('projects', 'pipeline_status')
    op.drop_column('projects', 'current_stage_id')
    op.drop_column('projects', 'pipeline_template_id')
    op.drop_table('project_pipeline_stages')