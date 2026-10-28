"""Customer Module Phase 1 — RLS policies on all new customer module tables

Enables Row-Level Security on every table introduced in migrations 0053–0063.
Policy: tenant_id must match the session-local app.tenant_id setting.
The same pattern used in 0037 (form tables) and 0052 (phase-5 tables).

Revision ID: 0064
Revises: 0063
Create Date: 2026-05-17
"""

from alembic import op

revision = '0064'
down_revision = '0063'
branch_labels = None
depends_on = None

# Tables that have tenant_id and need RLS
# (field_visibility_rules uses cascade delete from field_definitions — still has tenant_id)
_TABLES = [
    ('field_definitions',         'fd_tenant'),
    ('field_visibility_rules',    'fvr_tenant'),
    ('customers',                 'cust_tenant'),
    ('customer_field_values',     'cfv_tenant'),
    ('customer_form_submissions', 'cfs_tenant'),
    ('payment_requests',          'pr_tenant'),
    ('payment_confirmations',     'pc_tenant'),
    ('project_stage_approvals',   'psa_tenant'),
    ('stage_field_completion',    'sfc_tenant'),
    ('external_task_logs',        'etl_tenant'),
    ('customer_audit_log',        'cal_tenant'),
]

_POLICY_SQL = (
    "USING ("
    "tenant_id = current_setting('app.tenant_id', TRUE)::uuid "
    "OR current_setting('app.tenant_id', TRUE) IS NULL "
    "OR current_setting('app.tenant_id', TRUE) = ''"
    ")"
)


def upgrade() -> None:
    for table, policy in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {policy} ON {table} {_POLICY_SQL}"
        )


def downgrade() -> None:
    for table, policy in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
