"""
Dynamic Form Builder — schema_migration_history (audit trail for dynamic DDL).

Each row is one executed change to a tenant's dynamic entity table
(`tenant_{tenant_id}_{machine_name}_data`). This table is the source of
truth for what was applied and whether it can be replayed in reverse.

Deliberate differences from the original draft of this migration
(DYNAMIC_FORM_BUILDER_PLAN_1.md / IMPLEMENTATION_PHASES.md §Phase 1):

- No `migration_file_path`, and `alembic_revision` is nullable with no unique
  index. Nothing writes an Alembic file at runtime: dynamic DDL executes
  transactionally through the request's own AsyncSession, because Alembic is
  a single global linear chain and every tenant would otherwise queue behind
  the others. `plan_hash` (sha256 of forward_sql) replaces the revision hash
  for idempotency and duplicate detection.
- `is_destructive` is recorded up front so the UI can flag a DROP COLUMN
  before it runs and so rollback can refuse an unsafe replay.
- RLS uses the 0029 semantics verbatim. The plan's version used only
  `tenant_id = current_setting('app.tenant_id', TRUE)::uuid`, which evaluates
  to NULL whenever the GUC is unset and would hide every row from Celery
  tasks, admin scripts and tests.

Revision ID: 0095
Revises: 0094
"""

from alembic import op

revision      = '0095'
down_revision = '0094'
branch_labels = None
depends_on    = None


CHANGE_TYPES = (
    'create_table',    # new dynamic entity table
    'add_column',
    'alter_column',
    'drop_column',
    'add_index',
    'add_constraint',
)

STATUSES = (
    'pending',         # planned, shown in the preview, not yet executed
    'in_progress',
    'applied',
    'failed',          # rolled back by the transaction that raised
    'rolled_back',     # was applied, has since been reverted
)


def _rls(table: str) -> None:
    """0029's policy, unchanged: unset/empty GUC means unfiltered, not empty."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
            OR current_setting('app.tenant_id', TRUE) IS NULL
            OR current_setting('app.tenant_id', TRUE) = ''
        )
        WITH CHECK (
            tenant_id = current_setting('app.tenant_id', TRUE)::uuid
        )
    """)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE schema_migration_history (
            id                     uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id              uuid          NOT NULL REFERENCES tenants(id)       ON DELETE CASCADE,
            schema_id              uuid          NOT NULL REFERENCES form_schemas(id) ON DELETE CASCADE,

            migration_name         varchar(100)  NOT NULL,
            plan_hash              char(64)      NOT NULL,
            alembic_revision       varchar(32),

            change_type            varchar(50)   NOT NULL
                                               CHECK (change_type IN ('create_table', 'add_column',
                                                                       'alter_column', 'drop_column',
                                                                       'add_index', 'add_constraint')),
            field_changes          jsonb         NOT NULL DEFAULT '[]'::jsonb,
            table_name             varchar(200),

            forward_sql            text          NOT NULL,
            rollback_sql           text,

            status                 varchar(20)   NOT NULL DEFAULT 'pending'
                                               CHECK (status IN ('pending', 'in_progress', 'applied',
                                                                 'failed', 'rolled_back')),
            is_destructive         boolean       NOT NULL DEFAULT false,
            error_message          text,
            execution_duration_ms  integer,

            applied_by             uuid          REFERENCES users(id) ON DELETE SET NULL,
            applied_at             timestamptz,
            rolled_back_at         timestamptz,
            rolled_back_by         uuid          REFERENCES users(id) ON DELETE SET NULL,

            created_at             timestamptz   NOT NULL DEFAULT now(),
            created_by             uuid          REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    # asyncpg refuses more than one command per execute(), so each COMMENT
    # is its own statement.
    op.execute("""
        COMMENT ON TABLE schema_migration_history IS
            'Audit trail of dynamic entity-table DDL executed by the Form Builder'
    """)
    op.execute("""
        COMMENT ON COLUMN schema_migration_history.plan_hash IS
            'sha256 of forward_sql; identifies a plan and detects duplicate execution'
    """)
    op.execute("""
        COMMENT ON COLUMN schema_migration_history.is_destructive IS
            'TRUE when the change can drop or narrow data (DROP COLUMN, type change, NOT NULL added)'
    """)
    op.execute("""
        COMMENT ON COLUMN schema_migration_history.alembic_revision IS
            'Informational only. No migration files are generated at runtime.'
    """)

    # History listing: newest first for one tenant + schema
    op.execute("""
        CREATE INDEX ix_schema_migration_history_tenant_schema
        ON schema_migration_history (tenant_id, schema_id, created_at DESC)
    """)
    # Rollback guard: "has anything been applied to this table since?"
    op.execute("""
        CREATE INDEX ix_schema_migration_history_table
        ON schema_migration_history (schema_id, table_name, created_at DESC)
    """)
    # Partial index: rows an operator or the executor still has to act on
    op.execute("""
        CREATE INDEX ix_schema_migration_history_open
        ON schema_migration_history (tenant_id, status, created_at DESC)
        WHERE status IN ('pending', 'in_progress', 'applied')
    """)

    _rls('schema_migration_history')


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON schema_migration_history")
    op.execute("ALTER TABLE schema_migration_history DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_schema_migration_history_open")
    op.execute("DROP INDEX IF EXISTS ix_schema_migration_history_table")
    op.execute("DROP INDEX IF EXISTS ix_schema_migration_history_tenant_schema")
    op.execute("DROP TABLE IF EXISTS schema_migration_history")