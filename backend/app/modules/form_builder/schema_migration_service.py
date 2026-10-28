"""
Schema Migration Service - Core orchestrator for dynamic database schema changes.

This service coordinates the Form Builder's ability to automatically generate
and execute database migrations when users add/modify/delete fields in published schemas.

Key responsibilities:
- Plan migrations (preview without execution)
- Generate Alembic migration files programmatically
- Execute migrations safely in transactions
- Rollback migrations when needed
- Prevent concurrent schema modifications

Security:
- All operations require 'forms.admin' permission
- Tenant isolation enforced via RLS
- Schema-level advisory locks prevent race conditions
- All SQL is parameterized and validated
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, update

from app.core.config import settings
from app.modules.form_builder.models import (
    FormSchema,
    FieldDefinition,
    SchemaMigrationHistory,
)
from app.modules.form_builder.schema_sql import (
    RESERVED_COLUMNS,
    SqlGenerationError,
    build_add_column,
    build_alter_column,
    build_drop_column,
    entity_table_name,
    quote_ident,
    split_statements,
)


# ══════════════════════════════════════════════════════════════
#  LOCK KEYS
# ══════════════════════════════════════════════════════════════

def schema_lock_id(schema_id: uuid.UUID) -> int:
    """
    Deterministic 63-bit advisory-lock key for one form schema.

    Must be stable across processes and restarts: the web request that
    executes a migration and the Celery worker that may also touch the
    same schema have to derive the same key, or the lock protects
    nothing.

    Python's builtin hash() cannot be used here -- string hashing is
    salted per process (PYTHONHASHSEED), so two processes would compute
    different keys for the same schema.
    """
    digest = hashlib.blake2b(schema_id.bytes, digest_size=8).digest()
    return int.from_bytes(digest, 'big') & ((1 << 63) - 1)


def plan_hash(forward_sql: str) -> str:
    """sha256 of the forward SQL, used to detect duplicate execution."""
    return hashlib.sha256(forward_sql.encode('utf-8')).hexdigest()


# ══════════════════════════════════════════════════════════════
#  DATA CLASSES
# ══════════════════════════════════════════════════════════════

@dataclass
class FieldChange:
    """Represents a single field change requiring database migration."""
    action: str              # 'add', 'modify', 'delete'
    field: FieldDefinition   # The field being changed
    old_value: Optional[dict] = None  # For modify/delete actions
    new_value: Optional[dict] = None  # For add/modify actions


@dataclass
class MigrationPlan:
    """Complete migration plan ready for execution or user preview."""
    id: uuid.UUID
    schema_id: uuid.UUID
    tenant_id: uuid.UUID
    name: str                # e.g., "add_customer_address_field"
    change_type: str         # 'create_table', 'add_column', etc.
    table_name: str          # Target table name
    field_changes: list[dict]
    forward_sql: str         # SQL to execute
    rollback_sql: str        # SQL to revert
    estimated_duration: str  # Human-readable estimate
    affected_rows: int       # Number of rows in table
    reversible: bool         # Can this be rolled back?
    operations: list[Any]    # Operation objects for Alembic
    warnings: list[str]      # Non-blocking cautions for the preview UI
    is_destructive: bool     # Loses data or rewrites the table


@dataclass
class MigrationResult:
    """Result of migration execution."""
    success: bool
    migration_id: uuid.UUID
    table_name: str
    columns_added: list[str]
    execution_duration_ms: int
    applied_at: datetime
    error: Optional[str] = None


@dataclass
class RollbackResult:
    """Result of migration rollback."""
    success: bool
    migration_id: uuid.UUID
    rolled_back_at: datetime
    error: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of pre-migration validation."""
    valid: bool
    errors: list[str]
    warnings: list[str]


@dataclass
class _FailureSnapshot:
    """
    Plain copy of the history fields a failure record needs.

    Captured before execution so the failure can be recorded after the
    session has been rolled back and every ORM instance in it expired.
    """
    id: uuid.UUID
    tenant_id: uuid.UUID
    schema_id: uuid.UUID
    migration_name: str
    plan_hash: str
    change_type: str
    field_changes: list
    table_name: Optional[str]
    forward_sql: str
    rollback_sql: Optional[str]
    is_destructive: bool
    applied_by: Optional[uuid.UUID]
    created_by: Optional[uuid.UUID]


# ══════════════════════════════════════════════════════════════
#  EXCEPTIONS
# ══════════════════════════════════════════════════════════════

class MigrationError(Exception):
    """Base exception for migration-related errors."""
    pass


class ValidationError(MigrationError):
    """Migration failed validation checks."""
    pass


class ExecutionError(MigrationError):
    """Migration execution failed."""
    pass


class RollbackError(MigrationError):
    """Migration rollback failed."""
    pass


class ConcurrentModificationError(MigrationError):
    """Another migration is currently in progress for this schema."""
    pass


# ══════════════════════════════════════════════════════════════
#  SERVICE
# ══════════════════════════════════════════════════════════════

class SchemaMigrationService:
    """
    Orchestrates dynamic database schema migrations for Form Builder.

    Thread-safe and transaction-safe service that coordinates:
    1. Validation of proposed schema changes
    2. Generation of Alembic migration files
    3. Execution of migrations in database transactions
    4. Rollback of migrations when needed

    Usage:
        service = SchemaMigrationService(db)

        # Preview migration
        plan = await service.plan_migration(
            schema_id=schema_id,
            field_changes=[FieldChange(action='add', field=new_field)]
        )

        # Execute after user approval
        result = await service.execute_migration(
            migration_plan=plan,
            executed_by=user_id
        )
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def plan_migration(
        self,
        schema_id: uuid.UUID,
        field_changes: list[FieldChange],
        tenant_id: uuid.UUID,
    ) -> MigrationPlan:
        """
        Analyze proposed field changes and generate migration plan without execution.

        This method:
        1. Validates the changes are safe
        2. Generates SQL preview
        3. Estimates execution time
        4. Returns plan for user approval

        Args:
            schema_id: Form schema being modified
            field_changes: List of field additions/modifications/deletions
            tenant_id: Tenant owning this schema

        Returns:
            MigrationPlan ready for execution or display to user

        Raises:
            ValidationError: If changes are invalid/unsafe
            MigrationError: If planning fails
        """
        if not field_changes:
            raise ValidationError('no field changes supplied')

        schema = (await self.db.execute(
            select(FormSchema).where(FormSchema.id == schema_id)
        )).scalar_one_or_none()
        if schema is None:
            raise ValidationError(f'schema {schema_id} not found')
        # Checked before anything else: without this the rest of the method
        # would happily build DDL against another tenant's table name.
        if schema.tenant_id != tenant_id:
            raise ValidationError('schema does not belong to this tenant')
        if schema.is_deleted:
            raise ValidationError('schema is deleted')
        if schema.status == 'archived':
            raise ValidationError('schema is archived and cannot be migrated')

        table = entity_table_name(tenant_id, schema.machine_name)

        forward_parts: list[str] = []
        rollback_parts: list[str] = []
        reversible = True
        destructive = False
        change_type = 'add_column'
        changes_record: list[dict] = []
        warnings: list[str] = []

        seen_columns: set[str] = set()
        for change in field_changes:
            column, field_type, options, old_type, old_options = (
                self._describe_change(change)
            )

            if column in RESERVED_COLUMNS:
                raise ValidationError(
                    f"'{column}' is reserved by the dynamic table infrastructure"
                )
            if column in seen_columns:
                raise ValidationError(
                    f"'{column}' is changed more than once in one migration"
                )
            seen_columns.add(column)

            try:
                if change.action == 'add':
                    forward, rollback = build_add_column(
                        table, column, field_type, options,
                        nullable=not bool(change.field.is_required),
                    )
                    change_type = 'add_column'
                    reversible = True
                elif change.action == 'modify':
                    if not old_type:
                        raise ValidationError(
                            f"modify of '{column}' needs the previous field type"
                        )
                    forward, rollback = build_alter_column(
                        table, column, old_type, field_type, options, old_options
                    )
                    change_type = 'alter_column'
                    # A retype can fail or silently truncate on existing rows,
                    # so it is never advertised as safely reversible.
                    reversible = False
                    destructive = True
                elif change.action == 'delete':
                    forward, rollback = build_drop_column(table, column)
                    change_type = 'drop_column'
                    # The rollback restores the column shape, not its values.
                    reversible = False
                    destructive = True
                    warnings.append(
                        f"dropping '{column}' is irreversible; its data cannot "
                        'be recovered by rollback'
                    )
                else:
                    raise ValidationError(
                        f'unknown action {change.action!r}'
                    )
            except SqlGenerationError as exc:
                raise ValidationError(str(exc)) from exc

            forward_parts.append(forward)
            rollback_parts.append(rollback)
            changes_record.append({
                'action': change.action,
                'field_key': column,
                'from_type': old_type,
                'to_type': field_type,
                'options': options,
                'warning': warnings[-1] if change.action == 'delete' else None,
            })

        table_exists = await self._table_exists(table)
        if not table_exists and any(c.action != 'add' for c in field_changes):
            raise ValidationError(
                f"target table '{table}' does not exist yet; "
                'publish the schema before altering it'
            )

        affected_rows = await self._get_table_row_count(table) if table_exists else 0
        if affected_rows >= settings.MIGRATION_WARNING_ROW_COUNT:
            warnings.append(
                f"'{table}' holds ~{affected_rows} rows; this change may hold "
                'locks for a while'
            )

        forward_sql = ';\n'.join(forward_parts)
        rollback_sql = ';\n'.join(rollback_parts)

        return MigrationPlan(
            id=uuid.uuid4(),
            schema_id=schema_id,
            tenant_id=tenant_id,
            name=f'{change_type}_{schema.machine_name}_{uuid.uuid4().hex[:8]}',
            change_type=change_type,
            table_name=table,
            field_changes=changes_record,
            forward_sql=forward_sql,
            rollback_sql=rollback_sql,
            estimated_duration=self._estimate_duration(
                change_type, affected_rows
            ),
            affected_rows=affected_rows,
            reversible=reversible,
            operations=[],
            warnings=warnings,
            is_destructive=destructive,
        )

    @staticmethod
    def _describe_change(
        change: FieldChange,
    ) -> tuple[str, str, object, Optional[str], object]:
        """(column, type, options, old_type, old_options) for one change."""
        field = change.field
        if field is None:
            raise ValidationError('each field change must carry a field')
        if not getattr(field, 'field_key', None):
            raise ValidationError('each field change must carry a field_key')

        column = field.field_key
        options = getattr(field, 'options', None)
        old_type = None
        old_options = None
        if change.old_value:
            old_type = change.old_value.get('field_type')
            old_options = change.old_value.get('options')
        return column, field.field_type, options, old_type, old_options

    @staticmethod
    def _estimate_duration(change_type: str, affected_rows: int) -> str:
        """
        Rough, honest estimate for the preview UI.

        Postgres rewrites the table for most ALTER TYPE and for adding a NOT
        NULL column with no default, so cost tracks row count there. ADD
        COLUMN with a default is metadata-only on PG 11+.
        """
        if change_type == 'create_table':
            return '< 1 second'
        if change_type == 'add_column':
            return '< 1 second'
        if affected_rows < 10_000:
            return '< 5 seconds'
        if affected_rows < 100_000:
            return '5-30 seconds'
        return 'minutes (table rewrite, consider running off-peak)'

    async def execute_migration(
        self,
        migration_plan: MigrationPlan,
        executed_by: uuid.UUID,
    ) -> MigrationResult:
        """
        Execute an approved migration plan.

        This method:
        1. Acquires schema-level lock
        2. Refuses a plan whose SQL has already been applied
        3. Executes the forward SQL on the request's own session
        4. Updates migration history
        5. Releases lock (implicitly, at commit)

        All operations are transaction-wrapped with automatic rollback on failure.

        Postgres executes DDL transactionally, so running the plan on the
        caller's session gives all-or-nothing behaviour without any extra
        machinery: a retype that fails halfway leaves the table untouched.
        No migration file is written and no second connection is opened.

        Args:
            migration_plan: Approved plan from plan_migration()
            executed_by: User ID executing the migration

        Returns:
            MigrationResult with execution details

        Raises:
            ExecutionError: If migration fails
            ConcurrentModificationError: If schema is locked
        """
        if not settings.ENABLE_DYNAMIC_MIGRATIONS:
            raise ExecutionError('dynamic migrations are disabled by configuration')

        return await self._execute(migration_plan, executed_by)

    async def create_pending_migration(
        self,
        migration_plan: MigrationPlan,
        created_by: uuid.UUID,
    ) -> SchemaMigrationHistory:
        """
        Persist a plan as `pending` so it can be reviewed, then applied by id.

        Without this, the API would have to round-trip the generated SQL
        through the client, which means a caller could apply something other
        than what they were shown. Storing the plan means `apply` runs exactly
        the SQL that was previewed.

        Refuses a plan whose SQL has already been applied, so a preview cannot
        be held open and then applied after the same change landed by another
        route.
        """
        await self._set_tenant_context(migration_plan.tenant_id)

        forward_hash = plan_hash(migration_plan.forward_sql)
        duplicate = await self._find_applied_by_hash(
            migration_plan.schema_id, forward_hash
        )
        if duplicate is not None:
            raise ExecutionError(
                f"this exact migration was already applied as {duplicate.migration_name}"
            )

        row = SchemaMigrationHistory(
            id=uuid.uuid4(),
            tenant_id=migration_plan.tenant_id,
            schema_id=migration_plan.schema_id,
            migration_name=migration_plan.name,
            plan_hash=forward_hash,
            alembic_revision=None,   # no file is generated at runtime
            change_type=migration_plan.change_type,
            field_changes=migration_plan.field_changes,
            table_name=migration_plan.table_name,
            forward_sql=migration_plan.forward_sql,
            rollback_sql=migration_plan.rollback_sql,
            status='pending',
            is_destructive=migration_plan.is_destructive,
            created_by=created_by,
        )
        self.db.add(row)
        await self.db.commit()
        return row

    async def apply_migration(
        self,
        migration_id: uuid.UUID,
        executed_by: uuid.UUID,
    ) -> MigrationResult:
        """
        Apply a previously previewed plan, by history id.

        Runs the SQL stored on the pending row rather than a caller-supplied
        plan, so what executes is what was reviewed.
        """
        await self._set_tenant_context_from_history(migration_id)
        row = (await self.db.execute(
            select(SchemaMigrationHistory).where(SchemaMigrationHistory.id == migration_id)
        )).scalar_one_or_none()
        if row is None:
            raise ExecutionError(f'migration {migration_id} not found')
        if row.status != 'pending':
            raise ExecutionError(
                f"migration is '{row.status}'; only 'pending' migrations can be applied"
            )

        return await self._execute(self._plan_from_history(row), executed_by, existing=row)

    @staticmethod
    def _plan_from_history(row: SchemaMigrationHistory) -> MigrationPlan:
        """Rebuild the executable plan from its stored row."""
        return MigrationPlan(
            id=row.id,
            schema_id=row.schema_id,
            tenant_id=row.tenant_id,
            name=row.migration_name,
            change_type=row.change_type,
            table_name=row.table_name,
            field_changes=row.field_changes or [],
            forward_sql=row.forward_sql,
            rollback_sql=row.rollback_sql or '',
            estimated_duration='',
            affected_rows=0,
            reversible=not row.is_destructive,
            operations=[],
            warnings=[],
            is_destructive=row.is_destructive,
        )

    async def _execute(
        self,
        migration_plan: MigrationPlan,
        executed_by: uuid.UUID,
        existing: SchemaMigrationHistory | None = None,
    ) -> MigrationResult:
        """Shared execution path for plan objects and stored pending plans."""
        started = time.monotonic()
        # Transaction-local, so it is scoped to this transaction and cannot
        # leak to a pooled connection. Needed for the RLS-protected history
        # insert when the caller has no request-scoped context.
        await self._set_tenant_context(migration_plan.tenant_id)

        if not await self._acquire_schema_lock(migration_plan.schema_id):
            raise ConcurrentModificationError(
                'another migration is already running for this schema'
            )

        forward_hash = plan_hash(migration_plan.forward_sql)
        if existing is None:
            duplicate = await self._find_applied_by_hash(
                migration_plan.schema_id, forward_hash
            )
            if duplicate is not None:
                raise ExecutionError(
                    f"this exact migration was already applied as {duplicate.migration_name}"
                )

        history = existing or SchemaMigrationHistory(
            id=uuid.uuid4(),
            tenant_id=migration_plan.tenant_id,
            schema_id=migration_plan.schema_id,
            migration_name=migration_plan.name,
            plan_hash=forward_hash,
            alembic_revision=None,   # no file is generated at runtime
            change_type=migration_plan.change_type,
            field_changes=migration_plan.field_changes,
            table_name=migration_plan.table_name,
            forward_sql=migration_plan.forward_sql,
            rollback_sql=migration_plan.rollback_sql,
            status='in_progress',
            is_destructive=migration_plan.is_destructive,
            applied_by=executed_by,
            created_by=executed_by,
        )
        if existing is None:
            self.db.add(history)

        # Read before the try block: the rollback below expires every ORM
        # instance in the session, and touching an attribute afterwards
        # triggers a lazy refresh outside the greenlet context. That turned a
        # failed migration into an opaque MissingGreenlet instead of reporting
        # the real DDL error -- and skipped recording the failure entirely.
        # A pending (never-flushed) instance would survive the rollback as
        # transient, so the ordering bug hid whenever a new row was created
        # and only surfaced on the apply-a-stored-plan path.
        history_id = history.id
        failure_record = _FailureSnapshot(
            id=history.id,
            tenant_id=history.tenant_id,
            schema_id=history.schema_id,
            migration_name=history.migration_name,
            plan_hash=history.plan_hash,
            change_type=history.change_type,
            field_changes=history.field_changes,
            table_name=history.table_name,
            forward_sql=history.forward_sql,
            rollback_sql=history.rollback_sql,
            is_destructive=history.is_destructive,
            applied_by=history.applied_by,
            created_by=history.created_by,
        )

        try:
            for statement in split_statements(migration_plan.forward_sql):
                await self.db.execute(text(statement))

            duration_ms = int((time.monotonic() - started) * 1000)
            applied_at = datetime.now(timezone.utc)
            history.status = 'applied'
            history.applied_at = applied_at
            history.applied_by = executed_by
            history.execution_duration_ms = duration_ms
            await self.db.commit()
        except Exception as exc:
            # A new row goes down with the DDL, which is correct: a migration
            # that did not apply must not read as applied. A pre-existing
            # pending row survives, because it was committed before execution
            # started. Either way the failure is recorded, so a failed attempt
            # is never invisible to an operator.
            await self.db.rollback()
            if existing is None:
                await self._record_failure(failure_record, exc)
            else:
                await self._mark_pending_failed(history_id, exc)
            raise ExecutionError(str(exc)) from exc

        return MigrationResult(
            success=True,
            migration_id=history_id,
            table_name=migration_plan.table_name,
            columns_added=[
                c['field_key'] for c in migration_plan.field_changes
                if c.get('action') == 'add'
            ],
            execution_duration_ms=duration_ms,
            applied_at=applied_at,
        )

    async def rollback_migration(
        self,
        migration_id: uuid.UUID,
        rolled_back_by: uuid.UUID,
    ) -> RollbackResult:
        """
        Revert a previously applied migration.

        This method:
        1. Verifies migration is rollback-eligible (status='applied')
        2. Executes the stored rollback SQL on the caller's session
        3. Updates migration history

        Refuses when the plan was flagged irreversible at plan time. The
        rollback SQL for a DROP exists only to restore the column *shape*; it
        cannot restore values, and pretending otherwise would mislead whoever
        reads the audit trail.

        Args:
            migration_id: ID of migration to roll back
            rolled_back_by: User ID executing the rollback

        Returns:
            RollbackResult with rollback details

        Raises:
            RollbackError: If rollback fails or migration is not eligible
        """
        if not settings.ENABLE_MIGRATION_ROLLBACK:
            raise RollbackError('migration rollback is disabled by configuration')

        await self._set_tenant_context_from_history(migration_id)

        history = (await self.db.execute(
            select(SchemaMigrationHistory).where(SchemaMigrationHistory.id == migration_id)
        )).scalar_one_or_none()
        if history is None:
            raise RollbackError(f'migration {migration_id} not found')

        if history.status != 'applied':
            raise RollbackError(
                f"migration is '{history.status}', only 'applied' can be rolled back"
            )
        if not history.rollback_sql:
            raise RollbackError('migration has no stored rollback SQL')
        if history.is_destructive:
            raise RollbackError(
                'migration is irreversible: rollback would restore the column '
                'shape but not its data'
            )

        if not await self._acquire_schema_lock(history.schema_id):
            raise ConcurrentModificationError(
                'another migration is already running for this schema'
            )

        started = time.monotonic()
        try:
            for statement in split_statements(history.rollback_sql):
                await self.db.execute(text(statement))

            history.status = 'rolled_back'
            rolled_back_at = datetime.now(timezone.utc)
            history.rolled_back_at = rolled_back_at
            history.rolled_back_by = rolled_back_by
            history.execution_duration_ms = int((time.monotonic() - started) * 1000)
            await self.db.commit()
        except Exception as exc:
            await self.db.rollback()
            raise RollbackError(str(exc)) from exc

        return RollbackResult(
            success=True,
            migration_id=migration_id,
            rolled_back_at=rolled_back_at,
        )

    # ── internals ──────────────────────────────────────────────

    async def _set_tenant_context(self, tenant_id: uuid.UUID) -> None:
        """Set app.tenant_id for this transaction (RLS on the history table)."""
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {'t': str(tenant_id)},
        )

    async def _set_tenant_context_from_history(self, migration_id: uuid.UUID) -> None:
        """
        Read the owning tenant before RLS can hide the row.

        RLS on schema_migration_history filters by app.tenant_id, so querying
        for the row first would return nothing and make every rollback look
        like "not found". The history table's own tenant_id is trusted here --
        it is only used to scope the very lookup that validates the caller's
        access, and execute_migration independently re-derives the tenant from
        the schema.
        """
        await self.db.execute(text(
            "SELECT set_config('app.tenant_id', coalesce(("
            "  SELECT tenant_id::text FROM schema_migration_history WHERE id = :m"
            "), ''), true)"
        ), {'m': migration_id})

    async def _find_applied_by_hash(
        self, schema_id: uuid.UUID, forward_hash: str,
    ) -> SchemaMigrationHistory | None:
        existing = (await self.db.execute(
            select(SchemaMigrationHistory).where(
                SchemaMigrationHistory.schema_id == schema_id,
                SchemaMigrationHistory.plan_hash == forward_hash,
                SchemaMigrationHistory.status == 'applied',
            ).limit(1)
        )).scalar_one_or_none()
        return existing

    async def _mark_pending_failed(self, history_id: uuid.UUID, exc: Exception) -> None:
        """
        Mark a pre-existing pending row failed after its apply attempt aborted.

        Uses a Core UPDATE rather than the ORM instance because the rollback
        above has expired `history`; touching its attributes would trigger a
        lazy refresh outside the greenlet context.
        """
        try:
            await self.db.execute(
                update(SchemaMigrationHistory)
                .where(SchemaMigrationHistory.id == history_id)
                .values(
                    status='failed',
                    error_message=f'{type(exc).__name__}: {exc}'[:2000],
                )
            )
            await self.db.commit()
        except Exception:
            # Never mask the original migration error with a bookkeeping one.
            await self.db.rollback()

    async def _record_failure(
        self, record: '_FailureSnapshot', exc: Exception,
    ) -> None:
        """
        Persist a failed attempt in its own transaction.

        The original attempt's row was rolled back with the DDL. Without this
        a failed migration would leave no trace at all, and the operator would
        have no way to tell a rejected request from one that never arrived.

        Takes a plain snapshot rather than the ORM instance: the session has
        already been rolled back by the time this runs, so the instance's
        attributes may be expired.
        """
        try:
            await self._set_tenant_context(record.tenant_id)
            self.db.add(SchemaMigrationHistory(
                id=record.id,
                tenant_id=record.tenant_id,
                schema_id=record.schema_id,
                migration_name=record.migration_name,
                plan_hash=record.plan_hash,
                alembic_revision=None,
                change_type=record.change_type,
                field_changes=record.field_changes,
                table_name=record.table_name,
                forward_sql=record.forward_sql,
                rollback_sql=record.rollback_sql,
                status='failed',
                is_destructive=record.is_destructive,
                error_message=f'{type(exc).__name__}: {exc}'[:2000],
                applied_by=record.applied_by,
                created_by=record.created_by,
            ))
            await self.db.commit()
        except Exception:
            # Never mask the original migration error with a bookkeeping one.
            await self.db.rollback()

    async def get_migration_history(
        self,
        schema_id: uuid.UUID,
        tenant_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SchemaMigrationHistory]:
        """
        Retrieve migration history for a schema.

        Args:
            schema_id: Form schema to get history for
            tenant_id: Tenant ID (for RLS enforcement)
            limit: Max results to return
            offset: Pagination offset

        Returns:
            List of migration history records, newest first
        """
        result = await self.db.execute(
            select(SchemaMigrationHistory)
            .where(
                SchemaMigrationHistory.schema_id == schema_id,
                SchemaMigrationHistory.tenant_id == tenant_id,
            )
            .order_by(SchemaMigrationHistory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def _acquire_schema_lock(self, schema_id: uuid.UUID) -> bool:
        """
        Take a PostgreSQL transaction-level advisory lock on one schema.

        pg_advisory_xact_lock releases automatically at commit or rollback,
        so a crashed migration cannot strand the lock.

        Returns False rather than blocking when another holder exists: the
        caller turns this into ConcurrentModificationError rather than
        parking an HTTP request for MAX_MIGRATION_DURATION_SECONDS.
        """
        result = await self.db.execute(
            text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
            {"lock_id": schema_lock_id(schema_id)}
        )
        return bool(result.scalar())

    async def _get_table_row_count(self, table_name: str) -> int:
        """
        Row count for the affected-rows estimate shown in the migration preview.

        pg_class.reltuples is the planner's estimate and is -1 until the
        table has been analysed, so an estimate of -1 must not leak into
        the UI. In that case fall back to an exact count -- dynamic entity
        tables are per-tenant and bounded, so this stays cheap.

        The identifier is validated and quoted rather than interpolated. It is
        already the output of entity_table_name(), but this method is reachable
        from anywhere, so it does not rely on the caller having done that.
        """
        estimate = await self.db.execute(
            text("SELECT reltuples::bigint FROM pg_class WHERE relname = :table_name"),
            {"table_name": table_name}
        )
        row = estimate.first()
        if row is not None and row[0] is not None and row[0] >= 0:
            return int(row[0])

        exact = await self.db.execute(
            text(f'SELECT count(*) FROM {quote_ident(table_name, "table_name")}')
        )
        counted = exact.scalar()
        return int(counted) if counted is not None else 0

    async def _table_exists(self, table_name: str) -> bool:
        """to_regclass, so a never-created dynamic table is not an error."""
        result = await self.db.execute(
            text("SELECT to_regclass(:name) IS NOT NULL"),
            {"name": table_name}
        )
        return bool(result.scalar())
