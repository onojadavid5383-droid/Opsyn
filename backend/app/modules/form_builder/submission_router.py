# ============================================================
# FORM BUILDER SUBMISSION ROUTER — Phase 4
# app/modules/form_builder/submission_router.py
#
# Registered in main.py at prefix /api/v1/form-builder
# (same prefix as router.py — FastAPI merges routes)
#
# Association Management:
#   POST   /associations                                 — create
#   GET    /associations                                 — list
#   GET    /associations/{association_id}                — get
#   PUT    /associations/{association_id}                — update
#   DELETE /associations/{association_id}                — soft delete
#
# Context lookup:
#   GET    /context/{context_type}/{context_id}/schemas  — published schemas for context
#
# Submission APIs (static paths BEFORE /{submission_id}):
#   POST   /submissions/validate                         — dry-run (no save)
#   POST   /submissions/draft                            — save / update draft
#   GET    /submissions/draft/latest                     — resume caller's draft
#   GET    /submissions/export                           — export schema workbook
#   GET    /submissions                                  — list (filterable)
#   POST   /submissions                                  — final submit
#   GET    /submissions/{submission_id}                  — get single
#   PATCH  /submissions/{submission_id}/approve          — approve
#   PATCH  /submissions/{submission_id}/reject           — reject
#   GET    /submissions/{submission_id}/export           — download as JSON
# ============================================================

from __future__ import annotations

import io
import json
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import check_permission
from app.modules.form_builder.models import (
    CONTEXT_TYPES,
    SUBMISSION_STATUSES,
    TRIGGER_EVENTS,
    FormAssociation,
    FormSchema,
    FormSchemaVersion,
    FormSubmission,
)
from app.modules.infrastructure.audit_service import write_audit_entry
from app.modules.staff.models import User
from app.modules.form_builder.validation_engine import (
    ValidationContext,
    validate,
)

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────

async def _load_schema(
    db: AsyncSession,
    schema_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> FormSchema:
    row = (await db.execute(
        select(FormSchema).where(
            FormSchema.id        == schema_id,
            FormSchema.tenant_id == tenant_id,
            FormSchema.is_deleted == False,
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schema not found.")
    return row


async def _audit_submission(
    db: AsyncSession,
    submission: FormSubmission,
    schema: FormSchema,
    caller: Any,
    action: str,
    *,
    old_data: dict[str, Any] | None = None,
) -> None:
    """Write form lifecycle events to the shared infrastructure audit stream."""
    actor = (await db.execute(
        select(User).where(User.id == caller.id).options(selectinload(User.staff_profile))
    )).scalar_one_or_none()
    await write_audit_entry(
        db,
        asset_type="form_submission",
        asset_id=submission.id,
        asset_key=schema.machine_name,
        action=action,
        actor_user=actor,
        old_data=old_data,
        new_data={"schema_id": str(schema.id), "status": submission.status, "data": submission.data or submission.draft_data or {}},
        tenant_id=caller.tenant_id,
    )


async def _load_current_version(
    db: AsyncSession,
    schema_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> FormSchemaVersion:
    version = (await db.execute(
        select(FormSchemaVersion).where(
            FormSchemaVersion.schema_id == schema_id,
            FormSchemaVersion.tenant_id == tenant_id,
            FormSchemaVersion.is_current == True,
        )
    )).scalar_one_or_none()
    if not version:
        raise HTTPException(400, "Schema has no published version. Publish it before accepting submissions.")
    return version


async def _snapshot_for_validation(
    db: AsyncSession,
    schema: FormSchema,
) -> tuple[FormSchemaVersion | None, list[dict]]:
    """
    Return (version, field_snapshot_list).
    Published schemas use the immutable version snapshot.
    Draft schemas use live field definitions (for dry-run / draft save).
    """
    if schema.status == "published" and schema.current_version > 0:
        version = (await db.execute(
            select(FormSchemaVersion).where(
                FormSchemaVersion.schema_id == schema.id,
                FormSchemaVersion.is_current == True,
                FormSchemaVersion.tenant_id == schema.tenant_id,
            )
        )).scalar_one_or_none()
        if version:
            return version, list(version.field_snapshot)

    # Draft: serialize live fields
    from app.modules.form_builder.router import _get_active_fields, _field_out  # noqa: PLC0415
    live = await _get_active_fields(db, schema.id)
    return None, [_field_out(f) for f in live]


def _caller_role_name(caller: Any) -> str:
    role = getattr(caller, "role", None)
    if role and hasattr(role, "name") and role.name:
        return str(role.name).lower()
    return "user"


async def _build_uniqueness_checker(
    db: AsyncSession,
    schema_id: uuid.UUID,
    tenant_id: uuid.UUID,
    snapshot: list[dict],
) -> Callable[[str, str, Any], bool]:
    """
    Pre-fetches submitted values for all fields with unique_in_schema=True,
    then returns a synchronous closure compatible with validate()'s
    uniqueness_checker parameter.

    The engine calls: uniqueness_checker(field_key, tenant_id, value) -> bool
    True  = value is unique (no duplicate found)
    False = duplicate exists
    """
    unique_fields = [
        fd["field_key"]
        for fd in snapshot
        if (fd.get("validation_rules") or {}).get("unique_in_schema")
    ]

    if not unique_fields:
        return lambda fkey, tid, value: True

    existing_rows = (await db.execute(
        select(FormSubmission.data).where(
            FormSubmission.schema_id  == schema_id,
            FormSubmission.tenant_id  == tenant_id,
            FormSubmission.is_deleted == False,
            FormSubmission.status     != "draft",
        )
    )).scalars().all()

    # Build {field_key: set_of_normalised_string_values}
    cache: dict[str, set[str]] = {fkey: set() for fkey in unique_fields}
    for row_data in existing_rows:
        if not isinstance(row_data, dict):
            continue
        for fkey in unique_fields:
            val = row_data.get(fkey)
            if val is not None:
                cache[fkey].add(str(val).strip().lower())

    def _checker(field_key: str, _tenant_id: str, value: Any) -> bool:
        existing = cache.get(field_key)
        if existing is None:
            return True
        return str(value).strip().lower() not in existing

    return _checker


# ── Serializers ───────────────────────────────────────────────

def _association_out(a: FormAssociation) -> dict:
    return {
        "id":                  str(a.id),
        "tenant_id":           str(a.tenant_id),
        "schema_id":           str(a.schema_id),
        "schema_version_id":   str(a.schema_version_id) if a.schema_version_id else None,
        "context_type":        a.context_type,
        "context_id":          str(a.context_id) if a.context_id else None,
        "context_label":       a.context_label,
        "is_mandatory":        a.is_mandatory,
        "display_order":       a.display_order,
        "trigger_event":       a.trigger_event,
        "auto_populate_fields": a.auto_populate_fields,
        "created_by":          str(a.created_by) if a.created_by else None,
        "created_at":          a.created_at.isoformat(),
        "updated_at":          a.updated_at.isoformat(),
    }


def _submission_out(s: FormSubmission) -> dict:
    return {
        "id":                str(s.id),
        "tenant_id":         str(s.tenant_id),
        "schema_id":         str(s.schema_id),
        "schema_version_id": str(s.schema_version_id) if s.schema_version_id else None,
        "entity_type":       s.entity_type,
        "entity_id":         str(s.entity_id) if s.entity_id else None,
        "association_id":    str(s.association_id) if s.association_id else None,
        "submitted_by":      str(s.submitted_by) if s.submitted_by else None,
        "submitted_at":      s.submitted_at.isoformat(),
        "status":            s.status,
        "data":              s.data,
        "draft_data":        s.draft_data,
        "approved_by":       str(s.approved_by) if s.approved_by else None,
        "approved_at":       s.approved_at.isoformat() if s.approved_at else None,
        "rejection_reason":  s.rejection_reason,
        "is_deleted":        s.is_deleted,
        "created_at":        s.created_at.isoformat(),
        "updated_at":        s.updated_at.isoformat(),
    }


# ══════════════════════════════════════════════════════════════
#  ASSOCIATION MANAGEMENT
# ══════════════════════════════════════════════════════════════

class AssociationCreate(BaseModel):
    schema_id:            uuid.UUID
    schema_version_id:    Optional[uuid.UUID]  = None
    context_type:         str
    context_id:           Optional[uuid.UUID]  = None
    context_label:        str                  = Field(..., max_length=200)
    is_mandatory:         bool                 = False
    display_order:        int                  = 0
    trigger_event:        Optional[str]        = None
    auto_populate_fields: Optional[dict]       = None

    @field_validator("context_type")
    @classmethod
    def validate_context_type(cls, v: str) -> str:
        if v not in CONTEXT_TYPES:
            raise ValueError(f"context_type must be one of: {', '.join(CONTEXT_TYPES)}")
        return v

    @field_validator("trigger_event")
    @classmethod
    def validate_trigger_event(cls, v: str | None) -> str | None:
        if v is not None and v not in TRIGGER_EVENTS:
            raise ValueError(f"trigger_event must be one of: {', '.join(TRIGGER_EVENTS)}")
        return v


class AssociationUpdate(BaseModel):
    context_label:        Optional[str]  = Field(None, max_length=200)
    is_mandatory:         Optional[bool] = None
    display_order:        Optional[int]  = None
    trigger_event:        Optional[str]  = None
    auto_populate_fields: Optional[dict] = None

    @field_validator("trigger_event")
    @classmethod
    def validate_trigger_event(cls, v: str | None) -> str | None:
        if v is not None and v not in TRIGGER_EVENTS:
            raise ValueError(f"trigger_event must be one of: {', '.join(TRIGGER_EVENTS)}")
        return v


async def _get_association(
    db: AsyncSession,
    assoc_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> FormAssociation:
    row = (await db.execute(
        select(FormAssociation).where(
            FormAssociation.id        == assoc_id,
            FormAssociation.tenant_id == tenant_id,
            FormAssociation.is_deleted == False,
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Association not found.")
    return row


@router.post("/associations", status_code=status.HTTP_201_CREATED)
async def create_association(
    body: AssociationCreate,
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    schema = await _load_schema(db, body.schema_id, caller.tenant_id)
    if schema.status == "archived":
        raise HTTPException(400, "Cannot associate an archived schema.")

    assoc = FormAssociation(
        tenant_id           = caller.tenant_id,
        schema_id           = body.schema_id,
        schema_version_id   = body.schema_version_id,
        context_type        = body.context_type,
        context_id          = body.context_id,
        context_label       = body.context_label,
        is_mandatory        = body.is_mandatory,
        display_order       = body.display_order,
        trigger_event       = body.trigger_event,
        auto_populate_fields = body.auto_populate_fields,
        created_by          = caller.id,
    )
    db.add(assoc)
    await db.flush()
    await db.commit()
    return {"success": True, "data": _association_out(assoc)}


@router.get("/associations")
async def list_associations(
    schema_id:    Optional[uuid.UUID] = Query(None),
    context_type: Optional[str]       = Query(None),
    page:         int                 = Query(1, ge=1),
    limit:        int                 = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    if context_type and context_type not in CONTEXT_TYPES:
        raise HTTPException(400, f"Invalid context_type. Must be one of: {', '.join(CONTEXT_TYPES)}")

    conditions = [
        FormAssociation.tenant_id  == caller.tenant_id,
        FormAssociation.is_deleted == False,
    ]
    if schema_id:
        conditions.append(FormAssociation.schema_id == schema_id)
    if context_type:
        conditions.append(FormAssociation.context_type == context_type)

    total = (await db.execute(
        select(func.count(FormAssociation.id)).where(*conditions)
    )).scalar()

    rows = (await db.execute(
        select(FormAssociation)
        .where(*conditions)
        .order_by(FormAssociation.display_order, FormAssociation.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )).scalars().all()

    return {
        "success": True,
        "data":    [_association_out(a) for a in rows],
        "total":   total,
        "page":    page,
        "limit":   limit,
    }


@router.get("/associations/{association_id}")
async def get_association(
    association_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    assoc = await _get_association(db, association_id, caller.tenant_id)
    return {"success": True, "data": _association_out(assoc)}


@router.put("/associations/{association_id}")
async def update_association(
    association_id: uuid.UUID = Path(...),
    body: AssociationUpdate = ...,
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    assoc = await _get_association(db, association_id, caller.tenant_id)
    now = datetime.now(timezone.utc)
    if body.context_label        is not None: assoc.context_label        = body.context_label
    if body.is_mandatory         is not None: assoc.is_mandatory         = body.is_mandatory
    if body.display_order        is not None: assoc.display_order        = body.display_order
    if body.trigger_event        is not None: assoc.trigger_event        = body.trigger_event
    if body.auto_populate_fields is not None: assoc.auto_populate_fields = body.auto_populate_fields
    assoc.updated_at = now
    await db.flush()
    await db.commit()
    return {"success": True, "data": _association_out(assoc)}


@router.delete("/associations/{association_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_association(
    association_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    assoc = await _get_association(db, association_id, caller.tenant_id)
    assoc.is_deleted = True
    assoc.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.commit()


# ══════════════════════════════════════════════════════════════
#  CONTEXT LOOKUP
# ══════════════════════════════════════════════════════════════

@router.get("/context/{context_type}/{context_id}/schemas")
async def get_schemas_for_context(
    context_type: str       = Path(...),
    context_id:   uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    """Return all published schemas associated with a given context (e.g. pipeline stage, module)."""
    if context_type not in CONTEXT_TYPES:
        raise HTTPException(400, f"Invalid context_type. Must be one of: {', '.join(CONTEXT_TYPES)}")

    rows = (await db.execute(
        select(FormAssociation, FormSchema)
        .join(FormSchema, FormSchema.id == FormAssociation.schema_id)
        .where(
            FormAssociation.tenant_id    == caller.tenant_id,
            FormAssociation.context_type == context_type,
            or_(FormAssociation.context_id == context_id, FormAssociation.context_id.is_(None)),
            FormAssociation.is_deleted   == False,
            FormSchema.is_deleted        == False,
            FormSchema.status            == "published",
            FormSchema.tenant_id         == caller.tenant_id,
        )
        .order_by(FormAssociation.display_order, FormAssociation.created_at)
    )).all()

    return {
        "success": True,
        "data": [
            {
                "association": _association_out(assoc),
                "schema": {
                    "id":              str(schema.id),
                    "name":            schema.name,
                    "machine_name":    schema.machine_name,
                    "module":          schema.module,
                    "status":          schema.status,
                    "current_version": schema.current_version,
                    "is_mandatory":    assoc.is_mandatory,
                    "trigger_event":   assoc.trigger_event,
                },
            }
            for assoc, schema in rows
        ],
    }


# ══════════════════════════════════════════════════════════════
#  SUBMISSION APIs
#
# Route declaration order matters for FastAPI path matching:
#   /submissions/validate  (static)  ← FIRST
#   /submissions/draft     (static)  ← SECOND
#   /submissions           (no sub)  ← then list + create
#   /submissions/{id}      (dynamic) ← LAST
# ══════════════════════════════════════════════════════════════

class SubmitRequest(BaseModel):
    schema_id:            uuid.UUID
    entity_type:          str               = Field(..., max_length=50)
    entity_id:            Optional[uuid.UUID] = None
    association_id:       Optional[uuid.UUID] = None
    data:                 dict[str, Any]
    draft_id:             Optional[uuid.UUID] = None
    pipeline_stage_order: int               = 0


class DraftSaveRequest(BaseModel):
    schema_id:            uuid.UUID
    entity_type:          str               = Field(..., max_length=50)
    entity_id:            Optional[uuid.UUID] = None
    association_id:       Optional[uuid.UUID] = None
    data:                 dict[str, Any]
    draft_id:             Optional[uuid.UUID] = None  # if set, update existing draft
    pipeline_stage_order: int               = 0


class ValidateRequest(BaseModel):
    schema_id:            uuid.UUID
    data:                 dict[str, Any]
    pipeline_stage_order: int = 0
    is_draft:             bool = False


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1)


# ── POST /submissions/validate — dry-run ──────────────────────

@router.post("/submissions/validate")
async def validate_submission_dry_run(
    body: ValidateRequest,
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    """
    Validate data against a schema without persisting anything.
    Works with both published and draft schemas (for design-time testing).
    Returns the full ValidationResult including coerced_data.
    """
    schema           = await _load_schema(db, body.schema_id, caller.tenant_id)
    _version, snapshot = await _snapshot_for_validation(db, schema)

    if not snapshot:
        raise HTTPException(400, "Schema has no fields to validate against.")

    ctx = ValidationContext(
        tenant_id                  = str(caller.tenant_id),
        submitting_user_role       = _caller_role_name(caller),
        current_pipeline_stage_order = body.pipeline_stage_order,
        is_draft                   = body.is_draft,
    )
    uniqueness_checker = await _build_uniqueness_checker(
        db, schema.id, caller.tenant_id, snapshot,
    )
    result = validate(snapshot, body.data, ctx, uniqueness_checker=uniqueness_checker)

    return {
        "success":  True,
        "data": {
            "is_valid":               result.is_valid,
            "errors":                 [
                {
                    "field_key":   e.field_key,
                    "field_label": e.field_label,
                    "error_code":  e.error_code,
                    "message":     e.message,
                }
                for e in result.errors
            ],
            "warnings":               [
                {
                    "field_key": w.field_key,
                    "message":   w.message,
                }
                for w in result.warnings
            ],
            "missing_required_fields": result.missing_required_fields,
            "coerced_data":           result.coerced_data,
        },
    }


# ── POST /submissions/draft — save draft ─────────────────────

@router.post("/submissions/draft", status_code=status.HTTP_201_CREATED)
async def save_draft_submission(
    body: DraftSaveRequest,
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    """
    Save a draft submission. Required-field checks are skipped.
    If body.draft_id is provided and the draft exists for this tenant, it is updated.
    Otherwise a new draft submission is created.
    """
    schema           = await _load_schema(db, body.schema_id, caller.tenant_id)
    if schema.status == "archived":
        raise HTTPException(400, "Cannot submit to an archived schema.")

    version, snapshot = await _snapshot_for_validation(db, schema)

    ctx = ValidationContext(
        tenant_id                  = str(caller.tenant_id),
        submitting_user_role       = _caller_role_name(caller),
        current_pipeline_stage_order = body.pipeline_stage_order,
        is_draft                   = True,
    )
    uniqueness_checker = await _build_uniqueness_checker(
        db, schema.id, caller.tenant_id, snapshot,
    )
    result = validate(snapshot, body.data, ctx, uniqueness_checker=uniqueness_checker)

    # In draft mode only type_errors are fatal (required checks are skipped)
    type_errors = [e for e in result.errors if e.error_code == "type_error"]
    if type_errors:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Type coercion failed. Fix the listed fields before saving.",
                "errors":  [
                    {
                        "field_key":   e.field_key,
                        "field_label": e.field_label,
                        "error_code":  e.error_code,
                        "message":     e.message,
                    }
                    for e in type_errors
                ],
            },
        )

    now = datetime.now(timezone.utc)

    # Update existing draft if draft_id supplied and owned by caller
    if body.draft_id:
        existing = (await db.execute(
            select(FormSubmission).where(
                FormSubmission.id        == body.draft_id,
                FormSubmission.tenant_id == caller.tenant_id,
                FormSubmission.status    == "draft",
                FormSubmission.submitted_by == caller.id,
                FormSubmission.schema_id == schema.id,
                FormSubmission.entity_type == body.entity_type,
                FormSubmission.entity_id == body.entity_id,
                FormSubmission.association_id == body.association_id,
                FormSubmission.is_deleted == False,
            )
        )).scalar_one_or_none()
        if existing:
            old_data = {"status": existing.status, "data": existing.draft_data or {}}
            existing.draft_data  = result.coerced_data
            existing.updated_at  = now
            await db.flush()
            await _audit_submission(db, existing, schema, caller, "form_updated", old_data=old_data)
            await db.commit()
            return {"success": True, "data": _submission_out(existing)}

    # Create new draft
    sub = FormSubmission(
        tenant_id         = caller.tenant_id,
        schema_id         = schema.id,
        schema_version_id = version.id if version else None,
        entity_type       = body.entity_type,
        entity_id         = body.entity_id,
        association_id    = body.association_id,
        submitted_by      = caller.id,
        submitted_at      = now,
        status            = "draft",
        data              = {},
        draft_data        = result.coerced_data,
        created_by        = caller.id,
    )
    db.add(sub)
    await db.flush()
    await _audit_submission(db, sub, schema, caller, "form_updated")
    await db.commit()
    return {"success": True, "data": _submission_out(sub)}


@router.get("/submissions/draft/latest")
async def get_latest_draft(
    schema_id: uuid.UUID = Query(...),
    entity_type: str = Query(...),
    entity_id: Optional[uuid.UUID] = Query(None),
    association_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    conditions = [
        FormSubmission.tenant_id == caller.tenant_id,
        FormSubmission.schema_id == schema_id,
        FormSubmission.entity_type == entity_type,
        FormSubmission.entity_id == entity_id,
        FormSubmission.submitted_by == caller.id,
        FormSubmission.status == "draft",
        FormSubmission.is_deleted == False,
    ]
    conditions.append(FormSubmission.association_id == association_id)
    row = (await db.execute(
        select(FormSubmission).where(*conditions).order_by(FormSubmission.updated_at.desc()).limit(1)
    )).scalar_one_or_none()
    return {"success": True, "data": _submission_out(row) if row else None}


@router.get("/submissions/export")
async def export_submissions(
    schema_id: uuid.UUID = Query(...),
    sub_status: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    """Export non-draft schema submissions to an authenticated Excel workbook."""
    from openpyxl import Workbook

    schema = await _load_schema(db, schema_id, caller.tenant_id)
    conditions = [
        FormSubmission.tenant_id == caller.tenant_id,
        FormSubmission.schema_id == schema.id,
        FormSubmission.is_deleted == False,
        FormSubmission.status != "draft",
    ]
    if sub_status:
        if sub_status not in SUBMISSION_STATUSES:
            raise HTTPException(400, "Invalid submission status.")
        conditions.append(FormSubmission.status == sub_status)
    rows = (await db.execute(
        select(FormSubmission).where(*conditions).order_by(FormSubmission.submitted_at.asc())
    )).scalars().all()

    fields: dict[str, str] = {}
    snapshots = (await db.execute(
        select(FormSchemaVersion.field_snapshot).where(
            FormSchemaVersion.schema_id == schema.id,
            FormSchemaVersion.tenant_id == caller.tenant_id,
        ).order_by(FormSchemaVersion.version_number.desc())
    )).scalars().all()
    for snapshot in snapshots:
        for field in snapshot or []:
            fields.setdefault(field.get("field_key", ""), field.get("label") or field.get("field_key", ""))
    fields.pop("", None)
    for row in rows:
        for key in (row.data or {}):
            fields.setdefault(key, key)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Submissions"
    metadata = ["Submission ID", "Status", "Submitted At", "Entity Type", "Entity ID"]
    sheet.append(metadata + list(fields.values()))
    for row in rows:
        data = row.data or {}
        sheet.append([
            str(row.id), row.status, row.submitted_at.isoformat(), row.entity_type,
            str(row.entity_id) if row.entity_id else "",
            *[json.dumps(data.get(key), ensure_ascii=False, default=str) if isinstance(data.get(key), (dict, list)) else data.get(key) for key in fields],
        ])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    buffer = io.BytesIO()
    workbook.save(buffer)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in schema.machine_name)
    return StreamingResponse(
        io.BytesIO(buffer.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_submissions.xlsx"'},
    )


# ── GET /submissions — list ───────────────────────────────────

@router.get("/submissions")
async def list_submissions(
    schema_id:     Optional[uuid.UUID] = Query(None),
    entity_type:   Optional[str]       = Query(None),
    entity_id:     Optional[uuid.UUID] = Query(None),
    sub_status:    Optional[str]       = Query(None, alias="status"),
    page:          int                 = Query(1, ge=1),
    limit:         int                 = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    if sub_status and sub_status not in SUBMISSION_STATUSES:
        raise HTTPException(400, f"Invalid status. Must be one of: {', '.join(SUBMISSION_STATUSES)}")

    conditions = [
        FormSubmission.tenant_id  == caller.tenant_id,
        FormSubmission.is_deleted == False,
    ]
    if schema_id:
        conditions.append(FormSubmission.schema_id == schema_id)
    if entity_type:
        conditions.append(FormSubmission.entity_type == entity_type)
    if entity_id:
        conditions.append(FormSubmission.entity_id == entity_id)
    if sub_status:
        conditions.append(FormSubmission.status == sub_status)

    total = (await db.execute(
        select(func.count(FormSubmission.id)).where(*conditions)
    )).scalar()

    rows = (await db.execute(
        select(FormSubmission)
        .where(*conditions)
        .order_by(FormSubmission.submitted_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )).scalars().all()

    return {
        "success": True,
        "data":    [_submission_out(s) for s in rows],
        "total":   total,
        "page":    page,
        "limit":   limit,
    }


# ── POST /submissions — final submit ─────────────────────────

@router.post("/submissions", status_code=status.HTTP_201_CREATED)
async def submit_form(
    body: SubmitRequest,
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    """
    Submit a completed form. Schema must be published.
    Runs full validation (required checks, stage gating, conditional logic).
    Raises 422 if validation fails.
    Stores coerced data. Links to the current immutable version.
    """
    schema = await _load_schema(db, body.schema_id, caller.tenant_id)
    if schema.status != "published":
        raise HTTPException(400, "Only published schemas accept final submissions.")

    version = await _load_current_version(db, schema.id, caller.tenant_id)

    snapshot = list(version.field_snapshot)
    if not snapshot:
        raise HTTPException(400, "Schema version has no fields.")

    ctx = ValidationContext(
        tenant_id                  = str(caller.tenant_id),
        submitting_user_role       = _caller_role_name(caller),
        current_pipeline_stage_order = body.pipeline_stage_order,
        is_draft                   = False,
    )
    uniqueness_checker = await _build_uniqueness_checker(
        db, schema.id, caller.tenant_id, snapshot,
    )
    result = validate(snapshot, body.data, ctx, uniqueness_checker=uniqueness_checker)

    if not result.is_valid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Form validation failed.",
                "errors":  [
                    {
                        "field_key":   e.field_key,
                        "field_label": e.field_label,
                        "error_code":  e.error_code,
                        "message":     e.message,
                    }
                    for e in result.errors
                ],
                "warnings":               [
                    {"field_key": w.field_key, "message": w.message}
                    for w in result.warnings
                ],
                "missing_required_fields": result.missing_required_fields,
            },
        )

    now = datetime.now(timezone.utc)
    sub = None
    submission_old_data = None
    if body.draft_id:
        sub = (await db.execute(select(FormSubmission).where(
            FormSubmission.id == body.draft_id,
            FormSubmission.tenant_id == caller.tenant_id,
            FormSubmission.submitted_by == caller.id,
            FormSubmission.schema_id == schema.id,
            FormSubmission.entity_type == body.entity_type,
            FormSubmission.entity_id == body.entity_id,
            FormSubmission.association_id == body.association_id,
            FormSubmission.status == "draft",
            FormSubmission.is_deleted == False,
        ))).scalar_one_or_none()
        if not sub:
            raise HTTPException(404, "Draft not found or no longer available.")
        submission_old_data = {"status": sub.status, "data": sub.draft_data or {}}
        sub.schema_version_id = version.id
        sub.submitted_at = now
        sub.updated_at = now
        sub.status = "submitted"
        sub.data = result.coerced_data
        sub.draft_data = None
    else:
        sub = FormSubmission(
            tenant_id=caller.tenant_id, schema_id=schema.id, schema_version_id=version.id,
            entity_type=body.entity_type, entity_id=body.entity_id, association_id=body.association_id,
            submitted_by=caller.id, submitted_at=now, status="submitted",
            data=result.coerced_data, created_by=caller.id,
        )
        db.add(sub)
    await db.flush()
    await _audit_submission(
        db, sub, schema, caller,
        "form_updated" if submission_old_data is not None else "form_submitted",
        old_data=submission_old_data,
    )
    await db.commit()
    return {"success": True, "data": _submission_out(sub)}


# ── GET /submissions/{id} — get single ───────────────────────

@router.get("/submissions/{submission_id}")
async def get_submission(
    submission_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    sub = (await db.execute(
        select(FormSubmission).where(
            FormSubmission.id        == submission_id,
            FormSubmission.tenant_id == caller.tenant_id,
            FormSubmission.is_deleted == False,
        )
    )).scalar_one_or_none()
    if not sub:
        raise HTTPException(404, "Submission not found.")
    return {"success": True, "data": _submission_out(sub)}


# ── PATCH /submissions/{id}/approve ──────────────────────────

@router.patch("/submissions/{submission_id}/approve")
async def approve_submission(
    submission_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    sub = (await db.execute(
        select(FormSubmission).where(
            FormSubmission.id        == submission_id,
            FormSubmission.tenant_id == caller.tenant_id,
            FormSubmission.is_deleted == False,
        )
    )).scalar_one_or_none()
    if not sub:
        raise HTTPException(404, "Submission not found.")
    if sub.status != "submitted":
        raise HTTPException(400, f"Only 'submitted' submissions can be approved. Current status: '{sub.status}'.")

    now             = datetime.now(timezone.utc)
    old_data = {"status": sub.status, "data": sub.data}
    sub.status      = "approved"
    sub.approved_by = caller.id
    sub.approved_at = now
    sub.updated_at  = now
    await db.flush()
    schema = await _load_schema(db, sub.schema_id, caller.tenant_id)
    await _audit_submission(db, sub, schema, caller, "form_approved", old_data=old_data)
    await db.commit()
    return {"success": True, "data": _submission_out(sub)}


# ── PATCH /submissions/{id}/reject ───────────────────────────

@router.patch("/submissions/{submission_id}/reject")
async def reject_submission(
    submission_id: uuid.UUID = Path(...),
    body: RejectRequest = ...,
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    sub = (await db.execute(
        select(FormSubmission).where(
            FormSubmission.id        == submission_id,
            FormSubmission.tenant_id == caller.tenant_id,
            FormSubmission.is_deleted == False,
        )
    )).scalar_one_or_none()
    if not sub:
        raise HTTPException(404, "Submission not found.")
    if sub.status != "submitted":
        raise HTTPException(400, f"Only 'submitted' submissions can be rejected. Current status: '{sub.status}'.")

    now                  = datetime.now(timezone.utc)
    old_data = {"status": sub.status, "data": sub.data}
    sub.status           = "rejected"
    sub.rejection_reason = body.reason
    sub.updated_at       = now
    await db.flush()
    schema = await _load_schema(db, sub.schema_id, caller.tenant_id)
    await _audit_submission(db, sub, schema, caller, "form_rejected", old_data=old_data)
    await db.commit()
    return {"success": True, "data": _submission_out(sub)}


# ── GET /submissions/{id}/export ─────────────────────────────

@router.get("/submissions/{submission_id}/export")
async def export_submission(
    submission_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    """
    Download submission data as a JSON file.
    Content-Disposition: attachment — triggers browser download.
    """
    sub = (await db.execute(
        select(FormSubmission).where(
            FormSubmission.id        == submission_id,
            FormSubmission.tenant_id == caller.tenant_id,
            FormSubmission.is_deleted == False,
        )
    )).scalar_one_or_none()
    if not sub:
        raise HTTPException(404, "Submission not found.")

    export_data = {
        "export_version": "1.0",
        "submission_id":  str(sub.id),
        "schema_id":      str(sub.schema_id),
        "schema_version_id": str(sub.schema_version_id) if sub.schema_version_id else None,
        "entity_type":    sub.entity_type,
        "entity_id":      str(sub.entity_id) if sub.entity_id else None,
        "status":         sub.status,
        "submitted_at":   sub.submitted_at.isoformat(),
        "submitted_by":   str(sub.submitted_by) if sub.submitted_by else None,
        "data":           sub.data,
        "exported_at":    datetime.now(timezone.utc).isoformat(),
    }

    payload = json.dumps(export_data, indent=2, default=str).encode("utf-8")
    filename = f"submission_{submission_id}.json"

    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
