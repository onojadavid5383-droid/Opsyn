# ============================================================
# FORM BUILDER MIGRATION ROUTER
#   app/modules/form_builder/migration_router.py
#
# Registered in main.py at prefix /api/v1/form-builder
#
# Dynamic schema migration APIs. Every route requires the
# "forms.admin" feature permission, matching the other
# form_builder write endpoints, because each one changes real
# table structure for a whole tenant.
#
#   POST /schemas/{schema_id}/migrations/preview  — plan, persist as pending
#   GET  /schemas/{schema_id}/migrations          — history (paginated)
#   GET  /migrations/{migration_id}               — single migration + SQL
#   POST /migrations/{migration_id}/apply         — execute a pending plan
#   POST /migrations/{migration_id}/rollback      — revert an applied plan
#
# The preview/apply split is deliberate. A preview is persisted as
# `pending`, and apply runs the SQL stored on that row -- never SQL
# supplied by the client. Otherwise a caller could be shown one
# plan and apply another.
# ============================================================

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import check_permission
from app.modules.form_builder.models import (
    FieldDefinition,
    FormSchema,
    SchemaMigrationHistory,
)
from app.modules.form_builder.schema_migration_service import (
    ConcurrentModificationError,
    ExecutionError,
    FieldChange,
    MigrationPlan,
    RollbackError,
    SchemaMigrationService,
    ValidationError,
)

router = APIRouter()

# Statuses a caller may narrow a history listing to. Mirrors the
# ck_schema_migration_history_status constraint so an unknown value
# is a 400 here rather than an empty result set.
MIGRATION_STATUSES = (
    "pending", "in_progress", "applied", "failed", "rolled_back",
)


# ══════════════════════════════════════════════════════════════
#  REQUEST BODIES
# ══════════════════════════════════════════════════════════════

class FieldChangeRequest(BaseModel):
    """One field-level change inside a preview request."""
    action:    str                = Field(..., description="add | modify | delete")
    field_id:  uuid.UUID           = Field(..., description="FieldDefinition being changed")
    # Required for 'modify': the type before the change, so the
    # inverse SQL can be built. The service refuses a modify that
    # cannot state what it is modifying.
    from_type: Optional[str]       = None
    from_options: Optional[list]   = None


class MigrationPreviewRequest(BaseModel):
    """Preview a set of field changes as a reversible SQL plan."""
    changes: list[FieldChangeRequest] = Field(..., min_length=1)

    @field_validator("changes")
    @classmethod
    def validate_changes(cls, v: list[FieldChangeRequest]) -> list[FieldChangeRequest]:
        if not v:
            raise ValueError("at least one change is required")
        seen: set[uuid.UUID] = set()
        for change in v:
            if change.action not in ("add", "modify", "delete"):
                raise ValueError(
                    f"action must be add, modify or delete (got '{change.action}')"
                )
            if change.field_id in seen:
                raise ValueError(
                    f"field {change.field_id} appears more than once in one request"
                )
            seen.add(change.field_id)
        return v


# ══════════════════════════════════════════════════════════════
#  SERIALISERS
# ══════════════════════════════════════════════════════════════

def _migration_out(m: SchemaMigrationHistory, include_sql: bool = False) -> dict:
    """History row -> API dict. SQL is withheld from list responses."""
    out = {
        "id":            str(m.id),
        "schema_id":     str(m.schema_id),
        "migration_name": m.migration_name,
        "plan_hash":     m.plan_hash,
        "change_type":   m.change_type,
        "status":        m.status,
        "table_name":    m.table_name,
        "is_destructive": m.is_destructive,
        "field_changes": m.field_changes,
        "applied_by":    str(m.applied_by) if m.applied_by else None,
        "applied_at":    m.applied_at.isoformat() if m.applied_at else None,
        "rolled_back_at": m.rolled_back_at.isoformat() if m.rolled_back_at else None,
        "error_message": m.error_message,
        "execution_duration_ms": m.execution_duration_ms,
        "created_at":    m.created_at.isoformat() if m.created_at else None,
    }
    if include_sql:
        out["forward_sql"]  = m.forward_sql
        out["rollback_sql"] = m.rollback_sql
    return out


def _plan_out(plan: MigrationPlan, migration_id: uuid.UUID) -> dict:
    """Preview response. Carries the warnings the UI must surface."""
    return {
        "migration_id":       str(migration_id),
        "schema_id":          str(plan.schema_id),
        "migration_name":     plan.name,
        "change_type":        plan.change_type,
        "table_name":         plan.table_name,
        "forward_sql":        plan.forward_sql,
        "rollback_sql":       plan.rollback_sql,
        "field_changes":      plan.field_changes,
        "affected_rows":      plan.affected_rows,
        "estimated_duration": plan.estimated_duration,
        "reversible":         plan.reversible,
        "is_destructive":     plan.is_destructive,
        "warnings":           plan.warnings,
    }


# ══════════════════════════════════════════════════════════════
#  INTERNALS
# ══════════════════════════════════════════════════════════════

async def _load_schema(
    db: AsyncSession, schema_id: uuid.UUID, tenant_id: uuid.UUID
) -> FormSchema:
    """Fetch a live schema in this tenant. 404 otherwise.

    Every route starts here rather than trusting the schema id alone, so a
    cross-tenant id yields 404 instead of a migration against someone
    else's table.
    """
    schema = (await db.execute(
        select(FormSchema).where(
            FormSchema.id == schema_id,
            FormSchema.tenant_id == tenant_id,
            FormSchema.is_deleted == False,
        )
    )).scalar_one_or_none()
    if schema is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Schema not found."
        )
    return schema


async def _load_field(
    db: AsyncSession, field_id: uuid.UUID, schema: FormSchema,
    allow_deleted: bool = False,
) -> FieldDefinition:
    """
    Fetch a field in this schema, 404 otherwise.

    `allow_deleted` is for planning a DROP. A removed field is soft-deleted the
    moment the user deletes it, so by the time a client comes to plan the
    matching DROP COLUMN the row is already inactive and the plan is
    impossible to build -- the builder can only discover the removal by
    diffing against the published snapshot, which happens after the delete.

    It stays scoped to the same tenant and schema, and the caller is expected
    to pass it only for action='delete'; nothing else should reach a
    soft-deleted row through this helper.
    """
    query = select(FieldDefinition).where(
        FieldDefinition.id == field_id,
        FieldDefinition.schema_id == schema.id,
    )
    if not allow_deleted:
        query = query.where(FieldDefinition.is_deleted == False)

    field = (await db.execute(query)).scalar_one_or_none()
    if field is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Field {field_id} not found in this schema.",
        )
    return field


def _http_error(exc: Exception) -> HTTPException:
    """Map a service exception onto the right status code.

    Validation and conflict problems are 400/409, not 500: they are caused
    by the request, and a 500 would make a client bug look like a server
    outage.
    """
    if isinstance(exc, ValidationError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if isinstance(exc, ConcurrentModificationError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, ExecutionError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, RollbackError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))


# ══════════════════════════════════════════════════════════════
#  PREVIEW
# ══════════════════════════════════════════════════════════════

@router.post(
    "/schemas/{schema_id}/migrations/preview",
    status_code=status.HTTP_201_CREATED,
)
async def preview_migration(
    schema_id: uuid.UUID = Path(...),
    body: MigrationPreviewRequest = ...,
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    """
    Plan a set of field changes and persist the plan as `pending`.

    Nothing is executed. The response carries the exact forward and
    rollback SQL so the change can be reviewed before it is applied, and
    the returned migration_id is what /apply consumes.
    """
    schema = await _load_schema(db, schema_id, caller.tenant_id)
    service = SchemaMigrationService(db)

    changes: list[FieldChange] = []
    for req in body.changes:
        # Only a delete may plan against a soft-deleted field; see _load_field.
        field = await _load_field(
            db, req.field_id, schema, allow_deleted=(req.action == "delete")
        )
        old_value = None
        if req.action == "modify":
            # from_type must come from the request rather than the stored
            # field: for an 'add' the row may already have been edited in
            # the draft, and the plan has to describe the transition the
            # caller actually intends.
            old_value = {
                "field_type": req.from_type,
                "options": req.from_options,
            }
        changes.append(
            FieldChange(action=req.action, field=field, old_value=old_value)
        )

    try:
        plan = await service.plan_migration(schema.id, changes, caller.tenant_id)
        row = await service.create_pending_migration(plan, caller.id)
    except (ValidationError, ExecutionError) as exc:
        raise _http_error(exc) from exc

    return {"success": True, "data": _plan_out(plan, row.id)}


# ══════════════════════════════════════════════════════════════
#  APPLY / ROLLBACK
# ══════════════════════════════════════════════════════════════

@router.post("/migrations/{migration_id}/apply")
async def apply_migration(
    migration_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    """
    Execute a previously previewed plan.

    Runs the SQL stored on the pending row, so what executes is exactly
    what was reviewed. The whole thing is one transaction: either the
    table changes and the row reads `applied`, or neither happened.
    """
    # Confirms the migration belongs to this tenant before any DDL. Without
    # it the id alone would be enough to run DDL against another tenant's
    # table.
    await _load_migration(db, migration_id, caller.tenant_id)

    service = SchemaMigrationService(db)
    try:
        result = await service.apply_migration(migration_id, caller.id)
    except (ValidationError, ExecutionError, ConcurrentModificationError) as exc:
        raise _http_error(exc) from exc

    return {"success": True, "data": {
        "migration_id":          str(result.migration_id),
        "table_name":            result.table_name,
        "columns_added":         result.columns_added,
        "execution_duration_ms": result.execution_duration_ms,
        "applied_at":            result.applied_at.isoformat() if result.applied_at else None,
    }}


@router.post("/migrations/{migration_id}/rollback")
async def rollback_migration(
    migration_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    """
    Revert an applied migration.

    Refuses migrations flagged destructive at plan time: their rollback SQL
    restores a column's shape but not the values that were in it, so
    allowing it would promise a recovery that cannot happen.
    """
    await _load_migration(db, migration_id, caller.tenant_id)

    service = SchemaMigrationService(db)
    try:
        result = await service.rollback_migration(migration_id, caller.id)
    except (RollbackError, ConcurrentModificationError) as exc:
        raise _http_error(exc) from exc

    return {"success": True, "data": {
        "migration_id":    str(result.migration_id),
        "rolled_back_at":  result.rolled_back_at.isoformat() if result.rolled_back_at else None,
    }}


# ══════════════════════════════════════════════════════════════
#  HISTORY
# ══════════════════════════════════════════════════════════════

@router.get("/schemas/{schema_id}/migrations")
async def list_migrations(
    schema_id: uuid.UUID = Path(...),
    status_filter: Optional[str] = Query(
        None, alias="status",
        description="Filter by status",
    ),
    page:  int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    """
    Migration history for one schema, newest first.

    Read-only, so it uses plain authentication rather than the admin
    permission: a tenant member who can see a form should be able to see
    how its table got to its current shape. The SQL itself is withheld
    here and available only on the detail route.
    """
    schema = await _load_schema(db, schema_id, caller.tenant_id)

    if status_filter is not None and status_filter not in MIGRATION_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"status must be one of: {', '.join(MIGRATION_STATUSES)}",
        )

    conditions = [
        SchemaMigrationHistory.schema_id == schema.id,
        SchemaMigrationHistory.tenant_id == caller.tenant_id,
    ]
    if status_filter:
        conditions.append(SchemaMigrationHistory.status == status_filter)

    total = (await db.execute(
        select(func.count()).select_from(SchemaMigrationHistory).where(*conditions)
    )).scalar_one()

    rows = (await db.execute(
        select(SchemaMigrationHistory)
        .where(*conditions)
        .order_by(SchemaMigrationHistory.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )).scalars().all()

    return {
        "success": True,
        "data":    [_migration_out(m) for m in rows],
        "total":   total,
        "page":    page,
        "limit":   limit,
    }


@router.get("/migrations/{migration_id}")
async def get_migration(
    migration_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    """
    One migration, including its forward and rollback SQL.

    The SQL is destructive-capable surface (it shows what a rollback would
    run), so it sits behind the admin permission rather than plain auth.
    """
    row = await _load_migration(db, migration_id, caller.tenant_id)
    return {"success": True, "data": _migration_out(row, include_sql=True)}


async def _load_migration(
    db: AsyncSession, migration_id: uuid.UUID, tenant_id: uuid.UUID
) -> SchemaMigrationHistory:
    """Fetch a migration in this tenant. 404 otherwise."""
    row = (await db.execute(
        select(SchemaMigrationHistory).where(
            SchemaMigrationHistory.id == migration_id,
            SchemaMigrationHistory.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Migration not found."
        )
    return row
