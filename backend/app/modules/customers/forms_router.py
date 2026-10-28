# ============================================================
# OPSYN CUSTOMER FORMS API — app/modules/customers/forms_router.py
# Dynamic Form Builder: customer-pipeline-aware schema management
#
# Registered at prefix /api/v1/forms — MUST be registered in
# main.py BEFORE the existing forms_router (prefix /api/v1) to
# prevent path shadowing on GET /forms/{context}.
#
# Endpoints:
#   GET    /schemas                       — list active schemas (tenant-scoped)
#   POST   /schemas                       — create schema (admin only)
#   GET    /schemas/{schema_id}           — get schema + fields + visibility
#   PUT    /schemas/{schema_id}           — update schema (new version, archive old)
#   POST   /schemas/{schema_id}/fields    — add field definition
#   PUT    /fields/{field_id}             — update field + visibility rules
#   DELETE /fields/{field_id}             — soft-delete (blocked if data submitted)
#   GET    /fields/{field_id}/visibility  — get stage × dept visibility matrix
# ============================================================

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import check_permission
from app.modules.forms.models import FormSchema
from app.modules.customers.models import (
    FieldDefinition, FieldVisibilityRule, CustomerFormSubmission,
    CustomerAuditLog, VALID_FIELD_TYPES,
)
from app.modules.staff.models import User

router = APIRouter()

PREFIX = "/api/v1/forms"  # informational — applied in main.py


# ── Utilities ─────────────────────────────────────────────────

def _actor_label(user: Optional[User]) -> str:
    """Resolve display name following the mandatory pattern from architecture invariants."""
    if user is None:
        return 'System'
    if user.staff_profile:
        return user.staff_profile.full_name
    return user.username


def _role_name(user: User) -> str:
    """Return the caller's role name (lowercase) for roles_can_edit checks."""
    if user.role:
        return (user.role.name or '').lower()
    return ''


def _can_edit_field(fd: FieldDefinition, user: User) -> bool:
    """True if the caller's role is listed in roles_can_edit, or caller is admin."""
    role_level = user.role.level if user.role else 1
    if role_level >= 5:
        return True
    role = _role_name(user)
    roles = [r.lower() for r in (fd.roles_can_edit or [])]
    return role in roles


async def _get_active_schema(
    schema_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    *,
    require_active: bool = False,
) -> FormSchema:
    q = select(FormSchema).where(FormSchema.id == schema_id, FormSchema.tenant_id == tenant_id)
    if require_active:
        q = q.where(FormSchema.is_active == True)  # noqa: E712
    schema = (await db.execute(q)).scalar_one_or_none()
    if not schema:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form schema not found.")
    return schema


async def _get_field(
    field_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> FieldDefinition:
    fd = (await db.execute(
        select(FieldDefinition)
        .where(
            FieldDefinition.id == field_id,
            FieldDefinition.tenant_id == tenant_id,
            FieldDefinition.is_deleted == False,  # noqa: E712
        )
        .options(selectinload(FieldDefinition.visibility_rules))
    )).scalar_one_or_none()
    if not fd:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Field definition not found.")
    return fd


async def _emit_audit(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    actor: Optional[User],
    action: str,
    field_key: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    customer_id: Optional[uuid.UUID] = None,
) -> None:
    """Write a customer_audit_log row. Skipped for schema-level events (no customer)."""
    if customer_id is None:
        return  # customer_audit_log.customer_id is NOT NULL; schema events have no customer
    log = CustomerAuditLog(
        tenant_id   = tenant_id,
        customer_id = customer_id,
        actor_id    = actor.id if actor else None,
        action      = action,
        field_key   = field_key,
        old_value   = old_value,
        new_value   = new_value,
    )
    db.add(log)


# ── Serializers ───────────────────────────────────────────────

def _vr_dict(vr: FieldVisibilityRule) -> dict:
    return {
        "id":                   str(vr.id),
        "stage_order":          vr.stage_order,
        "department_id":        str(vr.department_id),
        "is_required_to_advance": vr.is_required_to_advance,
    }


def _field_dict(fd: FieldDefinition, *, include_visibility: bool = False) -> dict:
    d: dict = {
        "id":                      str(fd.id),
        "key":                     fd.key,
        "label":                   fd.label,
        "field_type":              fd.field_type,
        "validation_rules":        fd.validation_rules,
        "is_required":             fd.is_required,
        "owner_department_id":     str(fd.owner_department_id) if fd.owner_department_id else None,
        "visible_from_stage_order": fd.visible_from_stage_order,
        "roles_can_edit":          fd.roles_can_edit or [],
        "field_order":             fd.field_order,
        "created_at":              fd.created_at.isoformat() if fd.created_at else None,
        "updated_at":              fd.updated_at.isoformat() if fd.updated_at else None,
    }
    if include_visibility and fd.visibility_rules is not None:
        d["visibility_rules"] = [_vr_dict(vr) for vr in fd.visibility_rules]
    return d


def _schema_dict(s: FormSchema, fields: list[FieldDefinition] | None = None) -> dict:
    d: dict = {
        "id":            str(s.id),
        "context":       s.context,
        "version":       s.version,
        "is_active":     s.is_active,
        "is_published":  s.is_published,
        "title":         s.title,
        "description":   s.description,
        "department_id": str(s.department_id) if s.department_id else None,
        "created_by":    str(s.created_by) if s.created_by else None,
        "created_at":    s.created_at.isoformat() if s.created_at else None,
        "updated_at":    s.updated_at.isoformat() if s.updated_at else None,
    }
    if fields is not None:
        d["fields"] = [_field_dict(f, include_visibility=True) for f in fields]
    return d


# ── Pydantic schemas ──────────────────────────────────────────

class SchemaCreate(BaseModel):
    context:      str
    title:        str
    description:  Optional[str] = None
    department_id: Optional[uuid.UUID] = None

    @field_validator('context')
    @classmethod
    def check_context(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("context must not be blank.")
        return v

    @field_validator('title')
    @classmethod
    def check_title(cls, v: str) -> str:
        if len(v.strip()) < 2:
            raise ValueError("title must be at least 2 characters.")
        return v.strip()


class SchemaUpdate(BaseModel):
    title:        Optional[str]       = None
    description:  Optional[str]       = None
    department_id: Optional[uuid.UUID] = None


class VisibilityRuleIn(BaseModel):
    stage_order:           int
    department_id:         uuid.UUID
    is_required_to_advance: bool = False


class FieldCreate(BaseModel):
    key:                     str
    label:                   str
    field_type:              str
    is_required:             bool             = False
    validation_rules:        Optional[Any]    = None
    owner_department_id:     Optional[uuid.UUID] = None
    visible_from_stage_order: int             = 1
    roles_can_edit:          list[str]        = []
    field_order:             int              = 0
    visibility_rules:        list[VisibilityRuleIn] = []

    @field_validator('field_type')
    @classmethod
    def check_field_type(cls, v: str) -> str:
        if v not in VALID_FIELD_TYPES:
            raise ValueError(f"field_type must be one of: {', '.join(sorted(VALID_FIELD_TYPES))}")
        return v

    @field_validator('key')
    @classmethod
    def check_key(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if not cleaned.replace('_', '').replace('-', '').isalnum():
            raise ValueError("key must be alphanumeric with underscores/hyphens only.")
        return cleaned


class FieldUpdate(BaseModel):
    label:                   Optional[str]        = None
    is_required:             Optional[bool]        = None
    validation_rules:        Optional[Any]         = None
    owner_department_id:     Optional[uuid.UUID]   = None
    visible_from_stage_order: Optional[int]        = None
    roles_can_edit:          Optional[list[str]]   = None
    field_order:             Optional[int]         = None
    # If provided, replaces all existing visibility rules for this field
    visibility_rules:        Optional[list[VisibilityRuleIn]] = None


# ══════════════════════════════════════════════════════════════
# 1. GET /schemas — list active schemas
# ══════════════════════════════════════════════════════════════

@router.get("/schemas")
async def list_schemas(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(get_current_user),
):
    rows = (await db.execute(
        select(FormSchema)
        .where(FormSchema.tenant_id == caller.tenant_id)
        .order_by(FormSchema.context, FormSchema.version.desc())
    )).scalars().all()

    return {"success": True, "data": [_schema_dict(s) for s in rows]}


# ══════════════════════════════════════════════════════════════
# 2. POST /schemas — create new schema (admin only)
# ══════════════════════════════════════════════════════════════

@router.post("/schemas", status_code=status.HTTP_201_CREATED)
async def create_schema(
    body:   SchemaCreate = ...,
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("settings.admin")),
):
    # Determine next version for this context within this tenant
    latest_version = (await db.execute(
        select(func.max(FormSchema.version))
        .where(
            FormSchema.tenant_id == caller.tenant_id,
            FormSchema.context   == body.context,
        )
    )).scalar() or 0

    schema = FormSchema(
        tenant_id     = caller.tenant_id,
        context       = body.context,
        title         = body.title,
        description   = body.description,
        department_id = body.department_id,
        version       = latest_version + 1,
        is_published  = False,
        is_active     = False,
        created_by    = caller.id,
    )
    db.add(schema)
    await db.flush()

    await _emit_audit(
        db, caller.tenant_id, caller,
        action   = 'schema_created',
        new_value = body.title,
    )
    await db.commit()
    await db.refresh(schema)
    return {"success": True, "data": _schema_dict(schema, fields=[])}


# ══════════════════════════════════════════════════════════════
# 3. GET /schemas/{schema_id} — schema with fields + visibility
# ══════════════════════════════════════════════════════════════

@router.get("/schemas/{schema_id}")
async def get_schema(
    schema_id: uuid.UUID = Path(...),
    db:        AsyncSession = Depends(get_db),
    caller:    User         = Depends(get_current_user),
):
    schema = await _get_active_schema(schema_id, caller.tenant_id, db)

    # Load field definitions (not soft-deleted), with visibility rules
    fields = (await db.execute(
        select(FieldDefinition)
        .where(
            FieldDefinition.form_schema_id == schema_id,
            FieldDefinition.tenant_id      == caller.tenant_id,
            FieldDefinition.is_deleted     == False,  # noqa: E712
        )
        .options(selectinload(FieldDefinition.visibility_rules))
        .order_by(FieldDefinition.field_order)
    )).scalars().all()

    # Filter to fields the caller's role can see
    role_level = caller.role.level if caller.role else 1
    if role_level < 5:
        caller_role = _role_name(caller)
        fields = [
            f for f in fields
            if not f.roles_can_edit or caller_role in [r.lower() for r in f.roles_can_edit]
        ]

    return {"success": True, "data": _schema_dict(schema, fields=fields)}


# ══════════════════════════════════════════════════════════════
# 4. PUT /schemas/{schema_id} — update → new version, archive old
# ══════════════════════════════════════════════════════════════

@router.put("/schemas/{schema_id}")
async def update_schema(
    schema_id: uuid.UUID    = Path(...),
    body:      SchemaUpdate = ...,
    db:        AsyncSession = Depends(get_db),
    caller:    User         = Depends(check_permission("settings.admin")),
):
    old_schema = await _get_active_schema(schema_id, caller.tenant_id, db)

    # Archive the current version
    old_schema.is_active    = False
    old_schema.is_published = False
    old_schema.updated_at   = datetime.utcnow()

    # Create new version
    new_schema = FormSchema(
        tenant_id     = caller.tenant_id,
        context       = old_schema.context,
        title         = body.title        if body.title        is not None else old_schema.title,
        description   = body.description  if body.description  is not None else old_schema.description,
        department_id = body.department_id if body.department_id is not None else old_schema.department_id,
        version       = old_schema.version + 1,
        is_published  = False,
        is_active     = True,
        created_by    = caller.id,
    )
    db.add(new_schema)
    await db.flush()

    await _emit_audit(
        db, caller.tenant_id, caller,
        action    = 'schema_versioned',
        old_value = f"v{old_schema.version}: {old_schema.title}",
        new_value = f"v{new_schema.version}: {new_schema.title}",
    )
    await db.commit()
    await db.refresh(new_schema)
    return {
        "success": True,
        "data":    _schema_dict(new_schema, fields=[]),
        "archived_version": old_schema.version,
    }


# ══════════════════════════════════════════════════════════════
# 5. POST /schemas/{schema_id}/fields — add field definition
# ══════════════════════════════════════════════════════════════

@router.post("/schemas/{schema_id}/fields", status_code=status.HTTP_201_CREATED)
async def add_field(
    schema_id: uuid.UUID   = Path(...),
    body:      FieldCreate = ...,
    db:        AsyncSession = Depends(get_db),
    caller:    User         = Depends(check_permission("settings.admin")),
):
    schema = await _get_active_schema(schema_id, caller.tenant_id, db)

    # Enforce unique key within schema (among non-deleted fields)
    conflict = (await db.execute(
        select(FieldDefinition.id)
        .where(
            FieldDefinition.form_schema_id == schema_id,
            FieldDefinition.key            == body.key,
            FieldDefinition.is_deleted     == False,  # noqa: E712
        )
    )).scalar_one_or_none()
    if conflict:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Field key '{body.key}' already exists in this schema.",
        )

    fd = FieldDefinition(
        tenant_id               = caller.tenant_id,
        form_schema_id          = schema_id,
        key                     = body.key,
        label                   = body.label,
        field_type              = body.field_type,
        validation_rules        = body.validation_rules,
        is_required             = body.is_required,
        owner_department_id     = body.owner_department_id,
        visible_from_stage_order = body.visible_from_stage_order,
        roles_can_edit          = body.roles_can_edit,
        field_order             = body.field_order,
    )
    db.add(fd)
    await db.flush()

    # Insert visibility rules if provided
    for vr_in in body.visibility_rules:
        db.add(FieldVisibilityRule(
            tenant_id              = caller.tenant_id,
            field_definition_id    = fd.id,
            stage_order            = vr_in.stage_order,
            department_id          = vr_in.department_id,
            is_required_to_advance = vr_in.is_required_to_advance,
        ))

    schema.updated_at = datetime.utcnow()

    await _emit_audit(
        db, caller.tenant_id, caller,
        action    = 'field_created',
        field_key = body.key,
        new_value = f"{body.label} ({body.field_type})",
    )
    await db.commit()

    # Reload with visibility rules
    fd = await _get_field(fd.id, caller.tenant_id, db)
    return {"success": True, "data": _field_dict(fd, include_visibility=True)}


# ══════════════════════════════════════════════════════════════
# 6. PUT /fields/{field_id} — update field + optional visibility
# ══════════════════════════════════════════════════════════════

@router.put("/fields/{field_id}")
async def update_field(
    field_id: uuid.UUID   = Path(...),
    body:     FieldUpdate = ...,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(check_permission("settings.admin")),
):
    fd = await _get_field(field_id, caller.tenant_id, db)

    old_label = fd.label
    if body.label                   is not None: fd.label                    = body.label
    if body.is_required             is not None: fd.is_required              = body.is_required
    if body.validation_rules        is not None: fd.validation_rules         = body.validation_rules
    if body.owner_department_id     is not None: fd.owner_department_id      = body.owner_department_id
    if body.visible_from_stage_order is not None: fd.visible_from_stage_order = body.visible_from_stage_order
    if body.roles_can_edit          is not None: fd.roles_can_edit           = body.roles_can_edit
    if body.field_order             is not None: fd.field_order              = body.field_order
    fd.updated_at = datetime.utcnow()

    # Replace visibility rules if provided
    if body.visibility_rules is not None:
        for vr in list(fd.visibility_rules):
            await db.delete(vr)
        await db.flush()
        for vr_in in body.visibility_rules:
            db.add(FieldVisibilityRule(
                tenant_id              = caller.tenant_id,
                field_definition_id    = fd.id,
                stage_order            = vr_in.stage_order,
                department_id          = vr_in.department_id,
                is_required_to_advance = vr_in.is_required_to_advance,
            ))

    await _emit_audit(
        db, caller.tenant_id, caller,
        action    = 'field_updated',
        field_key = fd.key,
        old_value = old_label,
        new_value = fd.label,
    )
    await db.commit()

    fd = await _get_field(field_id, caller.tenant_id, db)
    return {"success": True, "data": _field_dict(fd, include_visibility=True)}


# ══════════════════════════════════════════════════════════════
# 7. DELETE /fields/{field_id} — soft-delete (blocked if data exists)
# ══════════════════════════════════════════════════════════════

@router.delete("/fields/{field_id}", status_code=status.HTTP_200_OK)
async def delete_field(
    field_id: uuid.UUID    = Path(...),
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(check_permission("settings.admin")),
):
    fd = await _get_field(field_id, caller.tenant_id, db)

    # Block deletion if any submission references this field key
    submission_count = (await db.execute(
        select(func.count(CustomerFormSubmission.id))
        .where(
            CustomerFormSubmission.tenant_id      == caller.tenant_id,
            CustomerFormSubmission.form_schema_id == fd.form_schema_id,
            CustomerFormSubmission.submitted_data[fd.key].as_string() != None,  # noqa: E711
        )
    )).scalar() or 0

    if submission_count > 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Cannot delete field '{fd.key}': {submission_count} customer submission(s) "
            f"contain data for this field. Archive the field instead.",
        )

    fd.is_deleted  = True
    fd.updated_at  = datetime.utcnow()

    await _emit_audit(
        db, caller.tenant_id, caller,
        action    = 'field_deleted',
        field_key = fd.key,
        old_value = fd.label,
    )
    await db.commit()
    return {"success": True, "message": f"Field '{fd.key}' soft-deleted."}


# ══════════════════════════════════════════════════════════════
# 8. POST /schemas/{schema_id}/publish — mark schema as published + active
# ══════════════════════════════════════════════════════════════

@router.post("/schemas/{schema_id}/publish")
async def publish_schema(
    schema_id: uuid.UUID = Path(...),
    db:        AsyncSession = Depends(get_db),
    caller:    User         = Depends(check_permission("settings.admin")),
):
    schema = (await db.execute(
        select(FormSchema)
        .where(FormSchema.id == schema_id, FormSchema.tenant_id == caller.tenant_id)
    )).scalar_one_or_none()
    if not schema:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form schema not found.")

    schema.is_published = True
    schema.is_active    = True
    schema.updated_at   = datetime.utcnow()

    await _emit_audit(
        db, caller.tenant_id, caller,
        action    = 'schema_published',
        new_value = schema.title,
    )
    await db.commit()
    await db.refresh(schema)
    return {"success": True, "data": _schema_dict(schema)}


# ══════════════════════════════════════════════════════════════
# 9. GET /fields/{field_id}/visibility — stage × dept matrix
# ══════════════════════════════════════════════════════════════

@router.get("/fields/{field_id}/visibility")
async def get_field_visibility(
    field_id: uuid.UUID    = Path(...),
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(get_current_user),
):
    fd = await _get_field(field_id, caller.tenant_id, db)
    return {
        "success": True,
        "data": {
            "field_id":       str(fd.id),
            "field_key":      fd.key,
            "visibility_rules": [_vr_dict(vr) for vr in fd.visibility_rules],
        },
    }
