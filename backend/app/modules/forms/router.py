# ============================================================
# OPSYN FORMS API — app/modules/forms/router.py
# Dynamic Form Builder: admin CRUD + user-facing submit/fetch
#
# S3.1.3 Admin endpoints (settings.admin required):
#   GET  /forms/{context}                                — get published schema
#   POST /admin/forms/{context}/fields                   — add field
#   PUT  /admin/forms/{context}/fields/{field_id}        — update field
#   DELETE /admin/forms/{context}/fields/{field_id}      — delete field
#   PATCH /admin/forms/{context}/fields/reorder          — reorder fields
#   POST /admin/forms/{context}/publish                  — publish draft
#   POST /admin/forms/{context}/dependencies             — add dependency
#   DELETE /admin/forms/{context}/dependencies/{dep_id}  — remove dependency
#
# S3.1.5 Submission endpoints:
#   POST /forms/submit                                   — submit form data
#   GET  /forms/submissions/{entity_type}/{entity_id}    — get submissions
# ============================================================

from __future__ import annotations
import uuid
from typing import Optional, Any
from datetime import datetime

from fastapi import APIRouter, Depends, Path, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import check_permission
from app.modules.forms.models import (
    FormSchema, FormField, FormFieldDependency, FormSubmission,
    VALID_FIELD_TYPES, VALID_CONTEXTS, VALID_OPERATORS, VALID_ACTIONS,
)
from app.modules.forms.validator import validate_submission

router = APIRouter()


# ── Serializers ───────────────────────────────────────────────


def _field_dict(f: FormField) -> dict:
    return {
        "id":               str(f.id),
        "field_key":        f.field_key,
        "field_type":       f.field_type,
        "label":            f.label,
        "placeholder":      f.placeholder,
        "help_text":        f.help_text,
        "required":         f.required,
        "field_order":      f.field_order,
        "options":          f.options,
        "validation_rules": f.validation_rules,
        "created_at":       f.created_at.isoformat() if f.created_at else None,
    }


def _dep_dict(d: FormFieldDependency) -> dict:
    return {
        "id":                 str(d.id),
        "source_field_key":   d.source_field_key,
        "target_field_key":   d.target_field_key,
        "condition_operator": d.condition_operator,
        "condition_value":    d.condition_value,
        "action":             d.action,
    }


def _schema_dict(s: FormSchema) -> dict:
    return {
        "id":           str(s.id),
        "context":      s.context,
        "version":      s.version,
        "is_published": s.is_published,
        "title":        s.title,
        "description":  s.description,
        "created_by":   str(s.created_by) if s.created_by else None,
        "created_at":   s.created_at.isoformat() if s.created_at else None,
        "updated_at":   s.updated_at.isoformat() if s.updated_at else None,
        "fields":       [_field_dict(f) for f in (s.fields or [])],
        "dependencies": [_dep_dict(d) for d in (s.dependencies or [])],
    }


# ── Helpers ───────────────────────────────────────────────────


async def _get_schema(
    db: AsyncSession, context: str, tenant_id: uuid.UUID,
    require_published: bool = False,
) -> FormSchema:
    if context not in VALID_CONTEXTS:
        raise HTTPException(400, f"Invalid context. Must be one of: {', '.join(sorted(VALID_CONTEXTS))}")

    q = (
        select(FormSchema)
        .where(FormSchema.tenant_id == tenant_id, FormSchema.context == context)
        .order_by(FormSchema.version.desc())
        .limit(1)
    )
    schema = (await db.execute(q)).scalar_one_or_none()

    if not schema:
        raise HTTPException(404, f"No form schema found for context '{context}'.")
    if require_published and not schema.is_published:
        raise HTTPException(404, f"No published form schema for context '{context}'.")
    return schema


# ══════════════════════════════════════════════════════════════
#  PUBLIC — GET published schema
# ══════════════════════════════════════════════════════════════

@router.get("/forms/{context}")
async def get_form_schema(
    context: str = Path(...),
    db: AsyncSession = Depends(get_db),
    caller = Depends(get_current_user),
):
    schema = await _get_schema(db, context, caller.tenant_id, require_published=True)
    return {"success": True, "data": _schema_dict(schema)}


# ══════════════════════════════════════════════════════════════
#  ADMIN — Fields
# ══════════════════════════════════════════════════════════════

class FieldCreate(BaseModel):
    field_key:        str
    field_type:       str
    label:            str
    placeholder:      Optional[str]  = None
    help_text:        Optional[str]  = None
    required:         bool           = False
    field_order:      int            = 0
    options:          Optional[Any]  = None
    validation_rules: Optional[Any]  = None

    @field_validator('field_type')
    @classmethod
    def check_field_type(cls, v: str) -> str:
        if v not in VALID_FIELD_TYPES:
            raise ValueError(f"field_type must be one of: {', '.join(sorted(VALID_FIELD_TYPES))}")
        return v

    @field_validator('field_key')
    @classmethod
    def check_field_key(cls, v: str) -> str:
        if not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError("field_key must be alphanumeric with underscores/hyphens only.")
        return v.lower()


class FieldUpdate(BaseModel):
    label:            Optional[str]  = None
    placeholder:      Optional[str]  = None
    help_text:        Optional[str]  = None
    required:         Optional[bool] = None
    field_order:      Optional[int]  = None
    options:          Optional[Any]  = None
    validation_rules: Optional[Any]  = None


class ReorderRequest(BaseModel):
    order: list[str]


@router.post("/admin/forms/{context}/fields", status_code=201)
async def add_form_field(
    context: str = Path(...),
    body: FieldCreate = ...,
    db: AsyncSession = Depends(get_db),
    caller = Depends(check_permission("settings.admin")),
):
    schema = await _get_schema(db, context, caller.tenant_id)

    # Enforce unique field_key within schema
    existing_keys = {f.field_key for f in schema.fields}
    if body.field_key in existing_keys:
        raise HTTPException(409, f"Field key '{body.field_key}' already exists in this schema.")

    field = FormField(
        tenant_id        = caller.tenant_id,
        schema_id        = schema.id,
        field_key        = body.field_key,
        field_type       = body.field_type,
        label            = body.label,
        placeholder      = body.placeholder,
        help_text        = body.help_text,
        required         = body.required,
        field_order      = body.field_order,
        options          = body.options,
        validation_rules = body.validation_rules,
    )
    db.add(field)
    schema.updated_at = datetime.utcnow()
    await db.flush()
    await db.commit()
    return {"success": True, "data": _field_dict(field)}


@router.put("/admin/forms/{context}/fields/{field_id}")
async def update_form_field(
    context: str = Path(...),
    field_id: uuid.UUID = Path(...),
    body: FieldUpdate = ...,
    db: AsyncSession = Depends(get_db),
    caller = Depends(check_permission("settings.admin")),
):
    schema = await _get_schema(db, context, caller.tenant_id)
    field  = (await db.execute(
        select(FormField).where(FormField.id == field_id, FormField.schema_id == schema.id)
    )).scalar_one_or_none()
    if not field:
        raise HTTPException(404, "Field not found.")

    if body.label            is not None: field.label            = body.label
    if body.placeholder      is not None: field.placeholder      = body.placeholder
    if body.help_text        is not None: field.help_text        = body.help_text
    if body.required         is not None: field.required         = body.required
    if body.field_order      is not None: field.field_order      = body.field_order
    if body.options          is not None: field.options          = body.options
    if body.validation_rules is not None: field.validation_rules = body.validation_rules

    schema.updated_at = datetime.utcnow()
    await db.flush()
    await db.commit()
    return {"success": True, "data": _field_dict(field)}


@router.delete("/admin/forms/{context}/fields/{field_id}", status_code=204)
async def delete_form_field(
    context: str = Path(...),
    field_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller = Depends(check_permission("settings.admin")),
):
    schema = await _get_schema(db, context, caller.tenant_id)
    result = await db.execute(
        delete(FormField).where(FormField.id == field_id, FormField.schema_id == schema.id)
    )
    if result.rowcount == 0:
        raise HTTPException(404, "Field not found.")
    schema.updated_at = datetime.utcnow()
    await db.commit()


@router.patch("/admin/forms/{context}/fields/reorder")
async def reorder_form_fields(
    context: str = Path(...),
    body: ReorderRequest = ...,
    db: AsyncSession = Depends(get_db),
    caller = Depends(check_permission("settings.admin")),
):
    schema = await _get_schema(db, context, caller.tenant_id)
    field_map = {str(f.id): f for f in schema.fields}

    for idx, field_id_str in enumerate(body.order):
        f = field_map.get(field_id_str)
        if f:
            f.field_order = idx

    schema.updated_at = datetime.utcnow()
    await db.flush()
    await db.commit()
    # Reload to reflect new order
    await db.refresh(schema)
    return {"success": True, "data": _schema_dict(schema)}


# ══════════════════════════════════════════════════════════════
#  ADMIN — Publish
# ══════════════════════════════════════════════════════════════

@router.post("/admin/forms/{context}/publish")
async def publish_form_schema(
    context: str = Path(...),
    db: AsyncSession = Depends(get_db),
    caller = Depends(check_permission("settings.admin")),
):
    schema = await _get_schema(db, context, caller.tenant_id)
    if schema.is_published:
        raise HTTPException(400, "Schema is already published.")
    if not schema.fields:
        raise HTTPException(400, "Cannot publish a schema with no fields.")

    schema.is_published = True
    schema.updated_at   = datetime.utcnow()
    await db.flush()
    await db.commit()
    return {"success": True, "data": _schema_dict(schema)}


# ══════════════════════════════════════════════════════════════
#  ADMIN — Dependencies
# ══════════════════════════════════════════════════════════════

class DependencyCreate(BaseModel):
    source_field_key:   str
    target_field_key:   str
    condition_operator: str
    condition_value:    Optional[str] = None
    action:             str

    @field_validator('condition_operator')
    @classmethod
    def check_operator(cls, v: str) -> str:
        if v not in VALID_OPERATORS:
            raise ValueError(f"condition_operator must be one of: {', '.join(sorted(VALID_OPERATORS))}")
        return v

    @field_validator('action')
    @classmethod
    def check_action(cls, v: str) -> str:
        if v not in VALID_ACTIONS:
            raise ValueError(f"action must be one of: {', '.join(sorted(VALID_ACTIONS))}")
        return v


@router.post("/admin/forms/{context}/dependencies", status_code=201)
async def add_form_dependency(
    context: str = Path(...),
    body: DependencyCreate = ...,
    db: AsyncSession = Depends(get_db),
    caller = Depends(check_permission("settings.admin")),
):
    schema = await _get_schema(db, context, caller.tenant_id)

    # Validate that both field keys exist in the schema
    existing_keys = {f.field_key for f in schema.fields}
    if body.source_field_key not in existing_keys:
        raise HTTPException(400, f"Source field '{body.source_field_key}' does not exist in this schema.")
    if body.target_field_key not in existing_keys:
        raise HTTPException(400, f"Target field '{body.target_field_key}' does not exist in this schema.")
    if body.source_field_key == body.target_field_key:
        raise HTTPException(400, "Source and target field keys must be different.")

    dep = FormFieldDependency(
        tenant_id          = caller.tenant_id,
        schema_id          = schema.id,
        source_field_key   = body.source_field_key,
        target_field_key   = body.target_field_key,
        condition_operator = body.condition_operator,
        condition_value    = body.condition_value,
        action             = body.action,
    )
    db.add(dep)
    schema.updated_at = datetime.utcnow()
    await db.flush()
    await db.commit()
    return {"success": True, "data": _dep_dict(dep)}


@router.delete("/admin/forms/{context}/dependencies/{dep_id}", status_code=204)
async def delete_form_dependency(
    context: str = Path(...),
    dep_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller = Depends(check_permission("settings.admin")),
):
    schema = await _get_schema(db, context, caller.tenant_id)
    result = await db.execute(
        delete(FormFieldDependency).where(
            FormFieldDependency.id == dep_id,
            FormFieldDependency.schema_id == schema.id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(404, "Dependency not found.")
    await db.commit()


# ══════════════════════════════════════════════════════════════
#  SUBMISSIONS — S3.1.5
# ══════════════════════════════════════════════════════════════

class SubmitFormRequest(BaseModel):
    context:        str
    entity_type:    Optional[str]          = None
    entity_id:      Optional[uuid.UUID]    = None
    submitted_data: dict[str, Any]


@router.post("/forms/submit", status_code=201)
async def submit_form(
    body: SubmitFormRequest,
    db: AsyncSession = Depends(get_db),
    caller = Depends(get_current_user),
):
    schema = await _get_schema(db, body.context, caller.tenant_id, require_published=True)

    # Serialize fields for validator
    field_defs = [
        {
            "field_key":        f.field_key,
            "field_type":       f.field_type,
            "required":         f.required,
            "options":          f.options,
            "validation_rules": f.validation_rules,
        }
        for f in schema.fields
    ]

    errors = validate_submission(field_defs, body.submitted_data)
    if errors:
        raise HTTPException(422, detail={"errors": errors})

    submission = FormSubmission(
        tenant_id      = caller.tenant_id,
        schema_id      = schema.id,
        entity_type    = body.entity_type,
        entity_id      = body.entity_id,
        submitted_by   = caller.id,
        submitted_data = body.submitted_data,
    )
    db.add(submission)
    await db.flush()
    await db.commit()

    return {
        "success": True,
        "data": {
            "id":           str(submission.id),
            "schema_id":    str(submission.schema_id),
            "entity_type":  submission.entity_type,
            "entity_id":    str(submission.entity_id) if submission.entity_id else None,
            "submitted_by": str(submission.submitted_by) if submission.submitted_by else None,
            "submitted_at": submission.submitted_at.isoformat(),
        },
    }


@router.get("/forms/submissions/{entity_type}/{entity_id}")
async def get_submissions(
    entity_type: str = Path(...),
    entity_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller = Depends(get_current_user),
):
    rows = (await db.execute(
        select(FormSubmission)
        .where(
            FormSubmission.tenant_id   == caller.tenant_id,
            FormSubmission.entity_type == entity_type,
            FormSubmission.entity_id   == entity_id,
        )
        .order_by(FormSubmission.submitted_at.desc())
    )).scalars().all()

    return {
        "success": True,
        "data": [
            {
                "id":             str(s.id),
                "schema_id":      str(s.schema_id),
                "submitted_by":   str(s.submitted_by) if s.submitted_by else None,
                "submitted_data": s.submitted_data,
                "submitted_at":   s.submitted_at.isoformat(),
            }
            for s in rows
        ],
    }
