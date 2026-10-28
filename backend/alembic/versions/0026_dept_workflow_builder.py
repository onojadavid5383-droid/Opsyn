"""
OPSYN DEPARTMENT WORKFLOW BUILDER MIGRATION
Revision: 0026

Creates:
  - dept_workflows table
  - dept_workflow_edges table
  - Alters project_pipeline_stages: makes template_stage_id nullable, adds workflow_edge_id
  - Alters projects: adds workflow_id
  - Adds updated_at trigger on dept_workflows

Run: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision      = '0026'
down_revision = '0025'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── dept_workflows ────────────────────────────────────────────────────────
    op.create_table(
        'dept_workflows',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text('gen_random_uuid()'),
        ),
        sa.Column('name',        sa.String(200), nullable=False),
        sa.Column('description', sa.Text(),      nullable=True),
        sa.Column(
            'trigger_dept_id',
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            'is_active',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('true'),
        ),
        sa.Column(
            'is_draft',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('true'),
        ),
        sa.Column(
            'version',
            sa.Integer(),
            nullable=False,
            server_default=sa.text('1'),
        ),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
    )

    op.create_foreign_key(
        'fk_dept_workflows_trigger_dept_id',
        'dept_workflows', 'departments',
        ['trigger_dept_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_dept_workflows_created_by',
        'dept_workflows', 'users',
        ['created_by'], ['id'],
        ondelete='SET NULL',
    )

    # Trigger for dept_workflows.updated_at
    op.execute("""
        CREATE TRIGGER update_dept_workflows_updated_at
            BEFORE UPDATE ON dept_workflows
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    # ── dept_workflow_edges ───────────────────────────────────────────────────
    op.create_table(
        'dept_workflow_edges',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text('gen_random_uuid()'),
        ),
        sa.Column(
            'workflow_id',
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            'from_dept_id',
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            'to_dept_id',
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column('edge_order',          sa.Integer(),     nullable=False),
        sa.Column('label',               sa.String(200),   nullable=True),
        sa.Column(
            'is_parallel',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
        sa.Column('parallel_group_id',   sa.String(50),    nullable=True),
        sa.Column('gate_requires_group', sa.String(50),    nullable=True),
        sa.Column(
            'can_push_back',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('true'),
        ),
        sa.Column('expected_days',       sa.Integer(),     nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
    )

    op.create_foreign_key(
        'fk_dept_workflow_edges_workflow_id',
        'dept_workflow_edges', 'dept_workflows',
        ['workflow_id'], ['id'],
        ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_dept_workflow_edges_from_dept_id',
        'dept_workflow_edges', 'departments',
        ['from_dept_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_dept_workflow_edges_to_dept_id',
        'dept_workflow_edges', 'departments',
        ['to_dept_id'], ['id'],
        ondelete='CASCADE',
    )

    op.create_unique_constraint(
        'uq_workflow_edge',
        'dept_workflow_edges',
        ['workflow_id', 'from_dept_id', 'to_dept_id'],
    )
    op.create_index(
        'ix_dept_workflow_edges_workflow_id',
        'dept_workflow_edges',
        ['workflow_id'],
    )

    # ── Alter project_pipeline_stages ─────────────────────────────────────────
    # Make template_stage_id nullable
    op.alter_column(
        'project_pipeline_stages',
        'template_stage_id',
        nullable=True,
    )

    # Add workflow_edge_id column
    op.add_column(
        'project_pipeline_stages',
        sa.Column(
            'workflow_edge_id',
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        'fk_project_pipeline_stages_workflow_edge_id',
        'project_pipeline_stages', 'dept_workflow_edges',
        ['workflow_edge_id'], ['id'],
        ondelete='SET NULL',
    )

    # ── Alter projects ────────────────────────────────────────────────────────
    op.add_column(
        'projects',
        sa.Column(
            'workflow_id',
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        'fk_projects_workflow_id',
        'projects', 'dept_workflows',
        ['workflow_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    # Revert projects.workflow_id
    op.drop_constraint('fk_projects_workflow_id', 'projects', type_='foreignkey')
    op.drop_column('projects', 'workflow_id')

    # Revert project_pipeline_stages changes
    op.drop_constraint(
        'fk_project_pipeline_stages_workflow_edge_id',
        'project_pipeline_stages',
        type_='foreignkey',
    )
    op.drop_column('project_pipeline_stages', 'workflow_edge_id')
    op.alter_column(
        'project_pipeline_stages',
        'template_stage_id',
        nullable=False,
    )

    # Revert dept_workflow_edges
    op.drop_index('ix_dept_workflow_edges_workflow_id', table_name='dept_workflow_edges')
    op.drop_constraint('uq_workflow_edge', 'dept_workflow_edges', type_='unique')
    op.drop_constraint('fk_dept_workflow_edges_to_dept_id',   'dept_workflow_edges', type_='foreignkey')
    op.drop_constraint('fk_dept_workflow_edges_from_dept_id', 'dept_workflow_edges', type_='foreignkey')
    op.drop_constraint('fk_dept_workflow_edges_workflow_id',  'dept_workflow_edges', type_='foreignkey')
    op.drop_table('dept_workflow_edges')

    # Revert dept_workflows
    op.execute("DROP TRIGGER IF EXISTS update_dept_workflows_updated_at ON dept_workflows;")
    op.drop_constraint('fk_dept_workflows_created_by',      'dept_workflows', type_='foreignkey')
    op.drop_constraint('fk_dept_workflows_trigger_dept_id', 'dept_workflows', type_='foreignkey')
    op.drop_table('dept_workflows')
