# ============================================================
# FORM BUILDER ROUTER — app/modules/form_builder/router.py
# Schema & Field Management APIs — Plan Phase 3
#
# Registered in main.py at prefix /api/v1/form-builder
# (BEFORE tasks_router; after infrastructure_router)
#
# Schema Management (§5.1):
#   POST   /schemas                                — create schema
#   GET    /schemas                                — list schemas (paginated)
#   GET    /schemas/{schema_id}                    — get schema + fields
#   PUT    /schemas/{schema_id}                    — update metadata
#   DELETE /schemas/{schema_id}                    — soft delete
#   POST   /schemas/{schema_id}/publish            — publish (version snapshot)
#   POST   /schemas/{schema_id}/archive            — archive
#   GET    /schemas/{schema_id}/versions           — list versions
#   GET    /schemas/{schema_id}/versions/{ver_id}  — get version snapshot
#   GET    /schemas/{schema_id}/renderer-config    — render-ready config
#
# Field Definition APIs (§5.2):
#   POST   /schemas/{schema_id}/fields             — add field
#   GET    /schemas/{schema_id}/fields             — list fields (ordered)
#   PATCH  /schemas/{schema_id}/fields/reorder     — reorder (BEFORE /{field_id})
#   GET    /schemas/{schema_id}/fields/{field_id}  — get field
#   PUT    /schemas/{schema_id}/fields/{field_id}  — update field
#   DELETE /schemas/{schema_id}/fields/{field_id}  — soft delete
#
# Utility:
#   GET    /field-types                            — 24-type catalogue
# ============================================================

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import check_permission
from app.modules.form_builder.models import (
    MODULES,
    SCHEMA_STATUSES,
    WIDTH_VALUES,
    FieldDefinition,
    FormSchema,
    FormSchemaVersion,
    FormSubmission,
)

router = APIRouter()

_MACHINE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_FIELD_KEY_RE    = re.compile(r"^[a-z][a-z0-9_]*$")


# ── Field-type catalogue ──────────────────────────────────────

FIELD_TYPE_CATALOGUE: list[dict] = [
    {"key": "string",         "label": "Short Text",           "category": "basic",      "has_options": False, "validation_rules": ["min_length", "max_length", "pattern"]},
    {"key": "text",           "label": "Long Text",            "category": "basic",      "has_options": False, "validation_rules": ["min_length", "max_length"]},
    {"key": "integer",        "label": "Integer",              "category": "basic",      "has_options": False, "validation_rules": ["min_value", "max_value"]},
    {"key": "float",          "label": "Decimal Number",       "category": "basic",      "has_options": False, "validation_rules": ["min_value", "max_value", "decimal_places"]},
    {"key": "boolean",        "label": "Yes / No",             "category": "basic",      "has_options": False, "validation_rules": []},
    {"key": "date",           "label": "Date",                 "category": "basic",      "has_options": False, "validation_rules": ["min_date", "max_date"]},
    {"key": "datetime",       "label": "Date & Time",          "category": "basic",      "has_options": False, "validation_rules": ["min_date", "max_date"]},
    {"key": "time",           "label": "Time",                 "category": "basic",      "has_options": False, "validation_rules": []},
    {"key": "email",          "label": "Email Address",        "category": "basic",      "has_options": False, "validation_rules": []},
    {"key": "phone",          "label": "Phone Number",         "category": "basic",      "has_options": False, "validation_rules": []},
    {"key": "url",            "label": "URL",                  "category": "basic",      "has_options": False, "validation_rules": []},
    {"key": "enum",           "label": "Dropdown",             "category": "choice",     "has_options": True,  "validation_rules": ["enum_options"]},
    {"key": "multiselect",    "label": "Multi-Select",         "category": "choice",     "has_options": True,  "validation_rules": ["enum_options", "min_count", "max_count"]},
    {"key": "radio",          "label": "Radio Buttons",        "category": "choice",     "has_options": True,  "validation_rules": ["enum_options"]},
    {"key": "file",           "label": "File Upload",          "category": "media",      "has_options": False, "validation_rules": ["allowed_types", "max_size_mb"]},
    {"key": "image",          "label": "Image Upload",         "category": "media",      "has_options": False, "validation_rules": ["max_size_mb"]},
    {"key": "signature",      "label": "Signature",            "category": "media",      "has_options": False, "validation_rules": []},
    {"key": "coordinates",    "label": "GPS Coordinates",      "category": "structured", "has_options": False, "validation_rules": []},
    {"key": "address",        "label": "Address",              "category": "structured", "has_options": False, "validation_rules": []},
    {"key": "currency",       "label": "Currency Amount",      "category": "structured", "has_options": False, "validation_rules": ["min_value", "max_value", "decimal_places"]},
    {"key": "rating",         "label": "Star Rating",          "category": "structured", "has_options": False, "validation_rules": ["min_rating", "max_rating"]},
    {"key": "lookup",         "label": "Lookup",               "category": "advanced",   "has_options": False, "validation_rules": []},
    {"key": "computed",       "label": "Computed (Read-only)", "category": "advanced",   "has_options": False, "validation_rules": []},
    {"key": "section_header", "label": "Section Header",       "category": "layout",     "has_options": False, "validation_rules": []},
]

_FIELD_TYPE_SET: frozenset[str] = frozenset(t["key"] for t in FIELD_TYPE_CATALOGUE)


# ── Serializers ───────────────────────────────────────────────

def _schema_out(s: FormSchema, fields: list[FieldDefinition] | None = None) -> dict:
    out: dict = {
        "id":              str(s.id),
        "tenant_id":       str(s.tenant_id),
        "name":            s.name,
        "machine_name":    s.machine_name,
        "description":     s.description,
        "module":          s.module,
        "status":          s.status,
        "current_version": s.current_version,
        "icon":            s.icon,
        "color":           s.color,
        "created_by":      str(s.created_by) if s.created_by else None,
        "created_at":      s.created_at.isoformat(),
        "updated_at":      s.updated_at.isoformat(),
    }
    if fields is not None:
        out["fields"] = [_field_out(f) for f in fields]
    return out


def _field_out(f: FieldDefinition) -> dict:
    return {
        "id":                str(f.id),
        "schema_id":         str(f.schema_id),
        "tenant_id":         str(f.tenant_id),
        "field_key":         f.field_key,
        "label":             f.label,
        "placeholder":       f.placeholder,
        "help_text":         f.help_text,
        "field_type":        f.field_type,
        "display_order":     f.display_order,
        "is_required":       f.is_required,
        "is_unique":         f.is_unique,
        "is_readonly":       f.is_readonly,
        "is_hidden":         f.is_hidden,
        "default_value":     f.default_value,
        "validation_rules":  f.validation_rules,
        "options":           f.options,
        "conditional_logic": f.conditional_logic,
        "role_visibility":   f.role_visibility,
        "role_editable":     f.role_editable,
        "stage_visible_from": f.stage_visible_from,
        "stage_required_at":  f.stage_required_at,
        "department_owner":  str(f.department_owner) if f.department_owner else None,
        "width":             f.width,
        "section_group":     f.section_group,
        "schema_version_id": str(f.schema_version_id) if f.schema_version_id else None,
        "created_by":        str(f.created_by) if f.created_by else None,
        "created_at":        f.created_at.isoformat(),
        "updated_at":        f.updated_at.isoformat(),
    }


def _version_out(v: FormSchemaVersion) -> dict:
    return {
        "id":             str(v.id),
        "schema_id":      str(v.schema_id),
        "tenant_id":      str(v.tenant_id),
        "version_number": v.version_number,
        "published_at":   v.published_at.isoformat() if v.published_at else None,
        "published_by":   str(v.published_by) if v.published_by else None,
        "field_snapshot": v.field_snapshot,
        "changelog":      v.changelog,
        "is_current":     v.is_current,
        "created_at":     v.created_at.isoformat(),
    }


# ── Internal helpers ──────────────────────────────────────────

async def _get_schema(
    db: AsyncSession,
    schema_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> FormSchema:
    row = (await db.execute(
        select(FormSchema).where(
            FormSchema.id == schema_id,
            FormSchema.tenant_id == tenant_id,
            FormSchema.is_deleted == False,
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schema not found.")
    return row


async def _get_active_fields(
    db: AsyncSession,
    schema_id: uuid.UUID,
) -> list[FieldDefinition]:
    rows = (await db.execute(
        select(FieldDefinition)
        .where(
            FieldDefinition.schema_id == schema_id,
            FieldDefinition.is_deleted == False,
        )
        .order_by(FieldDefinition.display_order, FieldDefinition.created_at)
    )).scalars().all()
    return list(rows)


# ══════════════════════════════════════════════════════════════
#  UTILITY — Field-type catalogue
# ══════════════════════════════════════════════════════════════

@router.get("/field-types")
async def list_field_types(caller=Depends(get_current_user)):
    """Return the canonical 24-type catalogue used by the validation engine."""
    return {"success": True, "data": FIELD_TYPE_CATALOGUE}


# ══════════════════════════════════════════════════════════════
#  §5.1 SCHEMA MANAGEMENT
# ══════════════════════════════════════════════════════════════

class SchemaCreate(BaseModel):
    name:         str            = Field(..., max_length=200)
    machine_name: str            = Field(..., max_length=100)
    description:  Optional[str] = None
    module:       str            = Field(..., max_length=50)
    icon:         Optional[str] = Field(None, max_length=50)
    color:        Optional[str] = Field(None, max_length=7)

    @field_validator("module")
    @classmethod
    def validate_module(cls, v: str) -> str:
        if v not in MODULES:
            raise ValueError(f"module must be one of: {', '.join(MODULES)}")
        return v

    @field_validator("machine_name")
    @classmethod
    def validate_machine_name(cls, v: str) -> str:
        if not _MACHINE_NAME_RE.match(v):
            raise ValueError(
                "machine_name must be lowercase alphanumeric + underscores, starting with a letter."
            )
        return v


class SchemaUpdate(BaseModel):
    name:        Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    icon:        Optional[str] = Field(None, max_length=50)
    color:       Optional[str] = Field(None, max_length=7)
    module:      Optional[str] = Field(None, max_length=50)

    @field_validator("module")
    @classmethod
    def validate_module(cls, v: str | None) -> str | None:
        if v is not None and v not in MODULES:
            raise ValueError(f"module must be one of: {', '.join(MODULES)}")
        return v


class PublishRequest(BaseModel):
    changelog: Optional[str] = None


@router.post("/schemas", status_code=status.HTTP_201_CREATED)
async def create_schema(
    body: SchemaCreate,
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    existing = (await db.execute(
        select(FormSchema.id).where(
            FormSchema.tenant_id   == caller.tenant_id,
            FormSchema.machine_name == body.machine_name,
            FormSchema.is_deleted  == False,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A schema with machine_name '{body.machine_name}' already exists in this tenant.",
        )

    schema = FormSchema(
        tenant_id    = caller.tenant_id,
        name         = body.name,
        machine_name = body.machine_name,
        description  = body.description,
        module       = body.module,
        status       = "draft",
        icon         = body.icon,
        color        = body.color,
        created_by   = caller.id,
    )
    db.add(schema)
    await db.flush()
    await db.commit()
    return {"success": True, "data": _schema_out(schema, fields=[])}


@router.get("/schemas")
async def list_schemas(
    module:        Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    search:        Optional[str] = Query(None),
    page:          int           = Query(1, ge=1),
    limit:         int           = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    if module and module not in MODULES:
        raise HTTPException(400, f"Invalid module. Must be one of: {', '.join(MODULES)}")
    if status_filter and status_filter not in SCHEMA_STATUSES:
        raise HTTPException(400, f"Invalid status. Must be one of: {', '.join(SCHEMA_STATUSES)}")

    conditions = [
        FormSchema.tenant_id == caller.tenant_id,
        FormSchema.is_deleted == False,
    ]
    if module:
        conditions.append(FormSchema.module == module)
    if status_filter:
        conditions.append(FormSchema.status == status_filter)
    if search:
        conditions.append(FormSchema.name.ilike(f"%{search}%"))

    total = (await db.execute(
        select(func.count(FormSchema.id)).where(*conditions)
    )).scalar()

    rows = (await db.execute(
        select(FormSchema)
        .where(*conditions)
        .order_by(FormSchema.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )).scalars().all()

    return {
        "success": True,
        "data":    [_schema_out(s) for s in rows],
        "total":   total,
        "page":    page,
        "limit":   limit,
    }


@router.get("/schemas/{schema_id}")
async def get_schema(
    schema_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    schema = await _get_schema(db, schema_id, caller.tenant_id)
    fields = await _get_active_fields(db, schema_id)
    return {"success": True, "data": _schema_out(schema, fields=fields)}


@router.put("/schemas/{schema_id}")
async def update_schema(
    schema_id: uuid.UUID = Path(...),
    body: SchemaUpdate = ...,
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    schema = await _get_schema(db, schema_id, caller.tenant_id)
    if schema.status == "archived":
        raise HTTPException(400, "Cannot update an archived schema.")

    if body.name        is not None: schema.name        = body.name
    if body.description is not None: schema.description = body.description
    if body.icon        is not None: schema.icon        = body.icon
    if body.color       is not None: schema.color       = body.color
    if body.module      is not None: schema.module      = body.module
    schema.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.commit()
    fields = await _get_active_fields(db, schema_id)
    return {"success": True, "data": _schema_out(schema, fields=fields)}


@router.delete("/schemas/{schema_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schema(
    schema_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    schema = await _get_schema(db, schema_id, caller.tenant_id)

    sub_count = (await db.execute(
        select(func.count(FormSubmission.id)).where(
            FormSubmission.schema_id == schema_id,
            FormSubmission.is_deleted == False,
        )
    )).scalar()
    if sub_count:
        raise HTTPException(409, "Cannot delete a schema that has existing submissions.")

    schema.is_deleted = True
    schema.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.commit()


@router.post("/schemas/{schema_id}/publish")
async def publish_schema(
    schema_id: uuid.UUID = Path(...),
    body: PublishRequest = Body(default=PublishRequest()),
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    """
    Create an immutable version snapshot of all current field definitions.
    Stamps every field with the new version id. Increments current_version.
    Sets status to 'published'. Deactivates any previous current version.
    """
    schema = await _get_schema(db, schema_id, caller.tenant_id)
    if schema.status == "archived":
        raise HTTPException(400, "Cannot publish an archived schema.")

    fields = await _get_active_fields(db, schema_id)
    if not fields:
        raise HTTPException(400, "Cannot publish a schema with no fields.")

    now               = datetime.now(timezone.utc)
    new_version_number = schema.current_version + 1

    # Deactivate all previously current versions (there should be at most one)
    await db.execute(
        sa_update(FormSchemaVersion)
        .where(
            FormSchemaVersion.schema_id == schema_id,
            FormSchemaVersion.is_current == True,
        )
        .values(is_current=False)
        .execution_options(synchronize_session=False)
    )

    # Immutable snapshot — JSONB copy of every field as of this moment
    snapshot = [_field_out(f) for f in fields]

    version = FormSchemaVersion(
        schema_id      = schema_id,
        tenant_id      = schema.tenant_id,
        version_number = new_version_number,
        published_at   = now,
        published_by   = caller.id,
        field_snapshot = snapshot,
        changelog      = body.changelog,
        is_current     = True,
        created_by     = caller.id,
    )
    db.add(version)
    await db.flush()  # required to get version.id before bulk update

    # Stamp all current fields with new version id
    await db.execute(
        sa_update(FieldDefinition)
        .where(
            FieldDefinition.schema_id == schema_id,
            FieldDefinition.is_deleted == False,
        )
        .values(schema_version_id=version.id, updated_at=now)
        .execution_options(synchronize_session=False)
    )

    schema.current_version = new_version_number
    schema.status          = "published"
    schema.updated_at      = now

    await db.flush()
    await db.commit()
    await db.refresh(version)
    return {"success": True, "data": _version_out(version)}


@router.post("/schemas/{schema_id}/archive")
async def archive_schema(
    schema_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    schema = await _get_schema(db, schema_id, caller.tenant_id)
    if schema.status == "archived":
        raise HTTPException(400, "Schema is already archived.")

    schema.status     = "archived"
    schema.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.commit()
    return {"success": True, "data": _schema_out(schema)}


@router.get("/schemas/{schema_id}/versions")
async def list_versions(
    schema_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    await _get_schema(db, schema_id, caller.tenant_id)
    rows = (await db.execute(
        select(FormSchemaVersion)
        .where(
            FormSchemaVersion.schema_id == schema_id,
            FormSchemaVersion.tenant_id == caller.tenant_id,
        )
        .order_by(FormSchemaVersion.version_number.desc())
    )).scalars().all()
    return {"success": True, "data": [_version_out(v) for v in rows]}


@router.get("/schemas/{schema_id}/versions/{version_id}")
async def get_version(
    schema_id:  uuid.UUID = Path(...),
    version_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    await _get_schema(db, schema_id, caller.tenant_id)
    version = (await db.execute(
        select(FormSchemaVersion).where(
            FormSchemaVersion.id        == version_id,
            FormSchemaVersion.schema_id == schema_id,
            FormSchemaVersion.tenant_id == caller.tenant_id,
        )
    )).scalar_one_or_none()
    if not version:
        raise HTTPException(404, "Version not found.")
    return {"success": True, "data": _version_out(version)}


@router.get("/schemas/{schema_id}/renderer-config")
async def get_renderer_config(
    schema_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    """
    Return everything the Form Renderer needs to display the form:
    schema metadata, current version info, ordered field config, and type catalogue.
    Published schemas serve from the immutable version snapshot.
    Draft schemas serve live fields for design-time preview.
    """
    schema = await _get_schema(db, schema_id, caller.tenant_id)

    if schema.status == "published" and schema.current_version > 0:
        version = (await db.execute(
            select(FormSchemaVersion).where(
                FormSchemaVersion.schema_id == schema_id,
                FormSchemaVersion.is_current == True,
                FormSchemaVersion.tenant_id == caller.tenant_id,
            )
        )).scalar_one_or_none()
        field_config = version.field_snapshot if version else []
        version_info = _version_out(version) if version else None
    else:
        live_fields  = await _get_active_fields(db, schema_id)
        field_config = [_field_out(f) for f in live_fields]
        version_info = None

    return {
        "success": True,
        "data": {
            "schema":      _schema_out(schema),
            "version":     version_info,
            "fields":      field_config,
            "field_types": FIELD_TYPE_CATALOGUE,
        },
    }


# ══════════════════════════════════════════════════════════════
#  §5.2 FIELD DEFINITION MANAGEMENT
# ══════════════════════════════════════════════════════════════

class FieldCreate(BaseModel):
    field_key:          str                    = Field(..., max_length=100)
    label:              str                    = Field(..., max_length=200)
    field_type:         str
    placeholder:        Optional[str]          = Field(None, max_length=300)
    help_text:          Optional[str]          = None
    display_order:      int                    = 0
    is_required:        bool                   = False
    is_unique:          bool                   = False
    is_readonly:        bool                   = False
    is_hidden:          bool                   = False
    default_value:      Optional[str]          = None
    validation_rules:   Optional[dict]         = None
    options:            Optional[Any]          = None
    conditional_logic:  Optional[dict]         = None
    role_visibility:    Optional[list[str]]    = None
    role_editable:      Optional[list[str]]    = None
    stage_visible_from: Optional[int]          = None
    stage_required_at:  Optional[int]          = None
    department_owner:   Optional[uuid.UUID]    = None
    width:              str                    = "full"
    section_group:      Optional[str]          = Field(None, max_length=100)

    @field_validator("field_type")
    @classmethod
    def validate_field_type(cls, v: str) -> str:
        if v not in _FIELD_TYPE_SET:
            raise ValueError(f"field_type must be one of: {', '.join(sorted(_FIELD_TYPE_SET))}")
        return v

    @field_validator("field_key")
    @classmethod
    def validate_field_key(cls, v: str) -> str:
        if not _FIELD_KEY_RE.match(v):
            raise ValueError(
                "field_key must be lowercase alphanumeric + underscores, starting with a letter."
            )
        return v

    @field_validator("width")
    @classmethod
    def validate_width(cls, v: str) -> str:
        if v not in WIDTH_VALUES:
            raise ValueError(f"width must be one of: {', '.join(WIDTH_VALUES)}")
        return v


class FieldUpdate(BaseModel):
    label:              Optional[str]          = Field(None, max_length=200)
    placeholder:        Optional[str]          = Field(None, max_length=300)
    help_text:          Optional[str]          = None
    display_order:      Optional[int]          = None
    is_required:        Optional[bool]         = None
    is_unique:          Optional[bool]         = None
    is_readonly:        Optional[bool]         = None
    is_hidden:          Optional[bool]         = None
    default_value:      Optional[str]          = None
    validation_rules:   Optional[dict]         = None
    options:            Optional[Any]          = None
    conditional_logic:  Optional[dict]         = None
    role_visibility:    Optional[list[str]]    = None
    role_editable:      Optional[list[str]]    = None
    stage_visible_from: Optional[int]          = None
    stage_required_at:  Optional[int]          = None
    department_owner:   Optional[uuid.UUID]    = None
    width:              Optional[str]          = None
    section_group:      Optional[str]          = None

    @field_validator("width")
    @classmethod
    def validate_width(cls, v: str | None) -> str | None:
        if v is not None and v not in WIDTH_VALUES:
            raise ValueError(f"width must be one of: {', '.join(WIDTH_VALUES)}")
        return v


class ReorderRequest(BaseModel):
    order: list[uuid.UUID]


@router.post("/schemas/{schema_id}/fields", status_code=status.HTTP_201_CREATED)
async def create_field(
    schema_id: uuid.UUID = Path(...),
    body: FieldCreate = ...,
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    schema = await _get_schema(db, schema_id, caller.tenant_id)
    if schema.status == "archived":
        raise HTTPException(400, "Cannot add fields to an archived schema.")

    existing = (await db.execute(
        select(FieldDefinition.id).where(
            FieldDefinition.schema_id == schema_id,
            FieldDefinition.field_key == body.field_key,
            FieldDefinition.is_deleted == False,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Field key '{body.field_key}' already exists in this schema.",
        )

    fld = FieldDefinition(
        schema_id          = schema_id,
        tenant_id          = schema.tenant_id,
        field_key          = body.field_key,
        label              = body.label,
        field_type         = body.field_type,
        placeholder        = body.placeholder,
        help_text          = body.help_text,
        display_order      = body.display_order,
        is_required        = body.is_required,
        is_unique          = body.is_unique,
        is_readonly        = body.is_readonly,
        is_hidden          = body.is_hidden,
        default_value      = body.default_value,
        validation_rules   = body.validation_rules or {},
        options            = body.options,
        conditional_logic  = body.conditional_logic,
        role_visibility    = body.role_visibility,
        role_editable      = body.role_editable,
        stage_visible_from = body.stage_visible_from,
        stage_required_at  = body.stage_required_at,
        department_owner   = body.department_owner,
        width              = body.width,
        section_group      = body.section_group,
        created_by         = caller.id,
    )
    db.add(fld)
    schema.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.commit()
    return {"success": True, "data": _field_out(fld)}


@router.get("/schemas/{schema_id}/fields")
async def list_fields(
    schema_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    await _get_schema(db, schema_id, caller.tenant_id)
    fields = await _get_active_fields(db, schema_id)
    return {"success": True, "data": [_field_out(f) for f in fields]}


# IMPORTANT: /reorder must be declared BEFORE /{field_id} so FastAPI matches
# the static literal "reorder" before attempting UUID coercion on {field_id}.
@router.patch("/schemas/{schema_id}/fields/reorder")
async def reorder_fields(
    schema_id: uuid.UUID = Path(...),
    body: ReorderRequest = ...,
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    await _get_schema(db, schema_id, caller.tenant_id)
    now = datetime.now(timezone.utc)
    for idx, field_id in enumerate(body.order):
        await db.execute(
            sa_update(FieldDefinition)
            .where(
                FieldDefinition.id == field_id,
                FieldDefinition.schema_id == schema_id,
                FieldDefinition.is_deleted == False,
            )
            .values(display_order=idx, updated_at=now)
            .execution_options(synchronize_session=False)
        )
    await db.commit()
    fields = await _get_active_fields(db, schema_id)
    return {"success": True, "data": [_field_out(f) for f in fields]}


@router.get("/schemas/{schema_id}/fields/{field_id}")
async def get_field(
    schema_id: uuid.UUID = Path(...),
    field_id:  uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(get_current_user),
):
    await _get_schema(db, schema_id, caller.tenant_id)
    fld = (await db.execute(
        select(FieldDefinition).where(
            FieldDefinition.id        == field_id,
            FieldDefinition.schema_id == schema_id,
            FieldDefinition.is_deleted == False,
        )
    )).scalar_one_or_none()
    if not fld:
        raise HTTPException(404, "Field not found.")
    return {"success": True, "data": _field_out(fld)}


@router.put("/schemas/{schema_id}/fields/{field_id}")
async def update_field(
    schema_id: uuid.UUID = Path(...),
    field_id:  uuid.UUID = Path(...),
    body: FieldUpdate = ...,
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    schema = await _get_schema(db, schema_id, caller.tenant_id)
    if schema.status == "archived":
        raise HTTPException(400, "Cannot modify fields of an archived schema.")

    fld = (await db.execute(
        select(FieldDefinition).where(
            FieldDefinition.id        == field_id,
            FieldDefinition.schema_id == schema_id,
            FieldDefinition.is_deleted == False,
        )
    )).scalar_one_or_none()
    if not fld:
        raise HTTPException(404, "Field not found.")

    now = datetime.now(timezone.utc)
    if body.label              is not None: fld.label              = body.label
    if body.placeholder        is not None: fld.placeholder        = body.placeholder
    if body.help_text          is not None: fld.help_text          = body.help_text
    if body.display_order      is not None: fld.display_order      = body.display_order
    if body.is_required        is not None: fld.is_required        = body.is_required
    if body.is_unique          is not None: fld.is_unique          = body.is_unique
    if body.is_readonly        is not None: fld.is_readonly        = body.is_readonly
    if body.is_hidden          is not None: fld.is_hidden          = body.is_hidden
    if body.default_value      is not None: fld.default_value      = body.default_value
    if body.validation_rules   is not None: fld.validation_rules   = body.validation_rules
    if body.options            is not None: fld.options            = body.options
    if body.conditional_logic  is not None: fld.conditional_logic  = body.conditional_logic
    if body.role_visibility    is not None: fld.role_visibility    = body.role_visibility
    if body.role_editable      is not None: fld.role_editable      = body.role_editable
    if body.stage_visible_from is not None: fld.stage_visible_from = body.stage_visible_from
    if body.stage_required_at  is not None: fld.stage_required_at  = body.stage_required_at
    if body.department_owner   is not None: fld.department_owner   = body.department_owner
    if body.width              is not None: fld.width              = body.width
    if body.section_group      is not None: fld.section_group      = body.section_group
    fld.updated_at    = now
    schema.updated_at = now
    await db.flush()
    await db.commit()
    return {"success": True, "data": _field_out(fld)}


@router.delete("/schemas/{schema_id}/fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_field(
    schema_id: uuid.UUID = Path(...),
    field_id:  uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_db),
    caller=Depends(check_permission("forms.admin")),
):
    schema = await _get_schema(db, schema_id, caller.tenant_id)
    if schema.status == "archived":
        raise HTTPException(400, "Cannot delete fields from an archived schema.")

    fld = (await db.execute(
        select(FieldDefinition).where(
            FieldDefinition.id        == field_id,
            FieldDefinition.schema_id == schema_id,
            FieldDefinition.is_deleted == False,
        )
    )).scalar_one_or_none()
    if not fld:
        raise HTTPException(404, "Field not found.")

    now               = datetime.now(timezone.utc)
    fld.is_deleted    = True
    fld.updated_at    = now
    schema.updated_at = now
    await db.flush()
    await db.commit()
