"""RLS for Phase 5 tables — task_department_routing, task_completion_approvals, archive_references

Revision ID: 0052
Revises: 0051
Create Date: 2026-05-17
"""

from alembic import op

revision = '0052'
down_revision = '0051'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, policy in (
        ('task_department_routing',  'tdr_tenant'),
        ('task_completion_approvals', 'tca_tenant'),
        ('archive_references',        'archref_tenant'),
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {policy} ON {table} "
            "USING (tenant_id::text = current_setting('app.tenant_id', TRUE))"
        )


def downgrade() -> None:
    for table, policy in (
        ('task_department_routing',  'tdr_tenant'),
        ('task_completion_approvals', 'tca_tenant'),
        ('archive_references',        'archref_tenant'),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
