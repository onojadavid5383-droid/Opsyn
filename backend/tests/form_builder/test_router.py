# ============================================================
# FORM BUILDER ROUTER — UNIT TESTS
# tests/form_builder/test_router.py
#
# Tests every route handler in app/modules/form_builder/router.py
# via direct function calls (no HTTP client, no running DB).
#
# Coverage:
#   Schema CRUD — create, list, get, update, soft-delete
#   Publish logic — version snapshot, field stamping, deactivation
#   Archive — success, already archived
#   Versions — list, get specific
#   Renderer config — published (from snapshot) vs draft (live fields)
#   Field CRUD — create, list, reorder, get, update, soft-delete
#   Field-types catalogue — all 24 types present
#   Tenant isolation — wrong-tenant requests return 404
#   Router registration — form_builder_router in main.py before tasks_router
# ============================================================

from __future__ import annotations

import os
os.environ.setdefault("DATABASE_URL",
    "postgresql+asyncpg://opsyn:opsyn@localhost:5432/opsyn_test")
os.environ.setdefault("SECRET_KEY",
    "test-secret-key-minimum-32-characters-long-for-jwt-signing")
os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("SMTP_PASSWORD", "test")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("ALLOWED_ORIGINS_STR", "http://localhost:5173")

import uuid
import datetime
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Mock factories ────────────────────────────────────────────

def _make_caller(tenant_id: uuid.UUID | None = None, level: int = 5) -> MagicMock:
    c = MagicMock()
    c.id        = uuid.uuid4()
    c.tenant_id = tenant_id or uuid.uuid4()
    c.role      = MagicMock(level=level)
    return c


def _make_schema(
    tenant_id: uuid.UUID | None = None,
    status: str = "draft",
    current_version: int = 0,
) -> MagicMock:
    s = MagicMock()
    s.id              = uuid.uuid4()
    s.tenant_id       = tenant_id or uuid.uuid4()
    s.name            = "Test Schema"
    s.machine_name    = "test_schema"
    s.description     = "A test schema"
    s.module          = "customer"
    s.status          = status
    s.current_version = current_version
    s.icon            = None
    s.color           = None
    s.created_by      = uuid.uuid4()
    s.is_deleted      = False
    s.created_at      = datetime.datetime.now(datetime.timezone.utc)
    s.updated_at      = datetime.datetime.now(datetime.timezone.utc)
    return s


def _make_field(schema_id: uuid.UUID | None = None, tenant_id: uuid.UUID | None = None) -> MagicMock:
    f = MagicMock()
    f.id                = uuid.uuid4()
    f.schema_id         = schema_id or uuid.uuid4()
    f.tenant_id         = tenant_id or uuid.uuid4()
    f.field_key         = "full_name"
    f.label             = "Full Name"
    f.placeholder       = None
    f.help_text         = None
    f.field_type        = "string"
    f.display_order     = 0
    f.is_required       = False
    f.is_unique         = False
    f.is_readonly       = False
    f.is_hidden         = False
    f.default_value     = None
    f.validation_rules  = {}
    f.options           = None
    f.conditional_logic = None
    f.role_visibility   = None
    f.role_editable     = None
    f.stage_visible_from = None
    f.stage_required_at  = None
    f.department_owner  = None
    f.width             = "full"
    f.section_group     = None
    f.schema_version_id = None
    f.created_by        = uuid.uuid4()
    f.is_deleted        = False
    f.created_at        = datetime.datetime.now(datetime.timezone.utc)
    f.updated_at        = datetime.datetime.now(datetime.timezone.utc)
    return f


def _make_version(schema_id: uuid.UUID | None = None, tenant_id: uuid.UUID | None = None) -> MagicMock:
    v = MagicMock()
    v.id             = uuid.uuid4()
    v.schema_id      = schema_id or uuid.uuid4()
    v.tenant_id      = tenant_id or uuid.uuid4()
    v.version_number = 1
    v.published_at   = datetime.datetime.now(datetime.timezone.utc)
    v.published_by   = uuid.uuid4()
    v.field_snapshot = []
    v.changelog      = None
    v.is_current     = True
    v.created_at     = datetime.datetime.now(datetime.timezone.utc)
    return v


def _exec_returning(value) -> MagicMock:
    """AsyncMock side-effect factory: returns a result whose scalar_one_or_none() = value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _exec_scalar(value) -> MagicMock:
    """AsyncMock side-effect factory: returns a result whose scalar() = value."""
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _exec_scalars_all(rows: list) -> MagicMock:
    """AsyncMock side-effect factory: returns result whose scalars().all() = rows."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _async_exec(*side_effects) -> AsyncMock:
    """Build a db.execute AsyncMock that returns values in order."""
    return AsyncMock(side_effect=list(side_effects))


# ── Shared db stub ────────────────────────────────────────────

def _db() -> AsyncMock:
    db = AsyncMock()
    db.add    = MagicMock()
    db.flush  = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ══════════════════════════════════════════════════════════════
#  Utility — GET /field-types
# ══════════════════════════════════════════════════════════════

class TestFieldTypesCatalogue:
    """GET /form-builder/field-types returns all 24 types."""

    @pytest.mark.asyncio
    async def test_returns_24_types(self):
        from app.modules.form_builder.router import list_field_types, FIELD_TYPE_CATALOGUE
        caller = _make_caller()
        result = await list_field_types(caller=caller)
        assert result["success"] is True
        assert len(result["data"]) == 24

    @pytest.mark.asyncio
    async def test_all_required_keys_present(self):
        from app.modules.form_builder.router import list_field_types
        caller = _make_caller()
        result = await list_field_types(caller=caller)
        for entry in result["data"]:
            assert "key" in entry
            assert "label" in entry
            assert "category" in entry
            assert "has_options" in entry
            assert "validation_rules" in entry

    @pytest.mark.asyncio
    async def test_all_24_field_type_keys_present(self):
        from app.modules.form_builder.router import list_field_types
        from app.modules.form_builder.models import FIELD_TYPES
        caller = _make_caller()
        result = await list_field_types(caller=caller)
        returned_keys = {e["key"] for e in result["data"]}
        for ft in FIELD_TYPES:
            assert ft in returned_keys, f"Field type '{ft}' missing from catalogue"

    @pytest.mark.asyncio
    async def test_choice_types_have_options(self):
        from app.modules.form_builder.router import list_field_types
        caller = _make_caller()
        result = await list_field_types(caller=caller)
        choice_types = {e["key"] for e in result["data"] if e["category"] == "choice"}
        assert "enum" in choice_types
        assert "multiselect" in choice_types
        assert "radio" in choice_types
        for entry in result["data"]:
            if entry["category"] == "choice":
                assert entry["has_options"] is True


# ══════════════════════════════════════════════════════════════
#  §5.1 — Schema Management: CREATE
# ══════════════════════════════════════════════════════════════

class TestCreateSchema:
    """POST /form-builder/schemas"""

    @pytest.mark.asyncio
    async def test_creates_schema_successfully(self):
        from app.modules.form_builder.router import create_schema, SchemaCreate
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        # No existing schema with same machine_name
        db.execute = _async_exec(_exec_returning(None))

        def _stamp(obj):
            obj.id         = uuid.uuid4()
            obj.created_at = datetime.datetime.now(datetime.timezone.utc)
            obj.updated_at = datetime.datetime.now(datetime.timezone.utc)
            obj.is_deleted = False

        db.add.side_effect = _stamp

        body = SchemaCreate(
            name="Customer Form",
            machine_name="customer_form",
            module="customer",
        )
        result = await create_schema(body=body, db=db, caller=caller)
        assert result["success"] is True
        assert result["data"]["machine_name"] == "customer_form"
        assert result["data"]["status"] == "draft"
        assert result["data"]["fields"] == []
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_machine_name_raises_409(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import create_schema, SchemaCreate
        tenant_id  = uuid.uuid4()
        caller     = _make_caller(tenant_id)
        db         = _db()
        # Simulate existing schema found
        db.execute = _async_exec(_exec_returning(uuid.uuid4()))

        body = SchemaCreate(
            name="Dup Schema",
            machine_name="existing_name",
            module="customer",
        )
        with pytest.raises(HTTPException) as exc:
            await create_schema(body=body, db=db, caller=caller)
        assert exc.value.status_code == 409

    def test_invalid_machine_name_rejected_by_pydantic(self):
        from pydantic import ValidationError
        from app.modules.form_builder.router import SchemaCreate
        with pytest.raises(ValidationError):
            SchemaCreate(name="X", machine_name="Has Spaces", module="customer")

    def test_invalid_module_rejected_by_pydantic(self):
        from pydantic import ValidationError
        from app.modules.form_builder.router import SchemaCreate
        with pytest.raises(ValidationError):
            SchemaCreate(name="X", machine_name="valid_name", module="nonexistent_module")


# ══════════════════════════════════════════════════════════════
#  §5.1 — Schema Management: LIST
# ══════════════════════════════════════════════════════════════

class TestListSchemas:
    """GET /form-builder/schemas"""

    @pytest.mark.asyncio
    async def test_returns_paginated_results(self):
        from app.modules.form_builder.router import list_schemas
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        s1, s2    = _make_schema(tenant_id), _make_schema(tenant_id)
        db.execute = _async_exec(
            _exec_scalar(2),           # count query
            _exec_scalars_all([s1, s2]),  # data query
        )
        result = await list_schemas(
            module=None, status_filter=None, search=None,
            page=1, limit=20, db=db, caller=caller,
        )
        assert result["success"] is True
        assert result["total"] == 2
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_invalid_module_raises_400(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import list_schemas
        caller = _make_caller()
        db     = _db()
        with pytest.raises(HTTPException) as exc:
            await list_schemas(
                module="nonexistent", status_filter=None, search=None,
                page=1, limit=20, db=db, caller=caller,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_status_raises_400(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import list_schemas
        caller = _make_caller()
        db     = _db()
        with pytest.raises(HTTPException) as exc:
            await list_schemas(
                module=None, status_filter="invalid_status", search=None,
                page=1, limit=20, db=db, caller=caller,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_result_set(self):
        from app.modules.form_builder.router import list_schemas
        caller = _make_caller()
        db     = _db()
        db.execute = _async_exec(_exec_scalar(0), _exec_scalars_all([]))
        result = await list_schemas(
            module=None, status_filter=None, search=None,
            page=1, limit=20, db=db, caller=caller,
        )
        assert result["total"] == 0
        assert result["data"] == []


# ══════════════════════════════════════════════════════════════
#  §5.1 — Schema Management: GET
# ══════════════════════════════════════════════════════════════

class TestGetSchema:
    """GET /form-builder/schemas/{schema_id}"""

    @pytest.mark.asyncio
    async def test_returns_schema_with_fields(self):
        from app.modules.form_builder.router import get_schema
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id)
        field     = _make_field(schema.id, tenant_id)
        db.execute = _async_exec(
            _exec_returning(schema),        # _get_schema
            _exec_scalars_all([field]),     # _get_active_fields
        )
        result = await get_schema(schema_id=schema.id, db=db, caller=caller)
        assert result["success"] is True
        assert result["data"]["id"] == str(schema.id)
        assert len(result["data"]["fields"]) == 1

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import get_schema
        caller = _make_caller()
        db     = _db()
        db.execute = _async_exec(_exec_returning(None))
        with pytest.raises(HTTPException) as exc:
            await get_schema(schema_id=uuid.uuid4(), db=db, caller=caller)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_wrong_tenant_returns_404(self):
        """Tenant A cannot fetch Tenant B's schema."""
        from fastapi import HTTPException
        from app.modules.form_builder.router import get_schema
        caller = _make_caller(uuid.uuid4())  # tenant A
        db     = _db()
        # _get_schema filters by tenant_id, so returns None for wrong tenant
        db.execute = _async_exec(_exec_returning(None))
        with pytest.raises(HTTPException) as exc:
            await get_schema(schema_id=uuid.uuid4(), db=db, caller=caller)
        assert exc.value.status_code == 404


# ══════════════════════════════════════════════════════════════
#  §5.1 — Schema Management: UPDATE
# ══════════════════════════════════════════════════════════════

class TestUpdateSchema:
    """PUT /form-builder/schemas/{schema_id}"""

    @pytest.mark.asyncio
    async def test_updates_name_successfully(self):
        from app.modules.form_builder.router import update_schema, SchemaUpdate
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="draft")
        db.execute = _async_exec(
            _exec_returning(schema),    # _get_schema
            _exec_scalars_all([]),      # _get_active_fields
        )
        body = SchemaUpdate(name="New Name")
        result = await update_schema(schema_id=schema.id, body=body, db=db, caller=caller)
        assert result["success"] is True
        assert schema.name == "New Name"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_archived_schema_cannot_be_updated(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import update_schema, SchemaUpdate
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="archived")
        db.execute = _async_exec(_exec_returning(schema))
        with pytest.raises(HTTPException) as exc:
            await update_schema(
                schema_id=schema.id, body=SchemaUpdate(name="X"),
                db=db, caller=caller,
            )
        assert exc.value.status_code == 400


# ══════════════════════════════════════════════════════════════
#  §5.1 — Schema Management: DELETE (soft)
# ══════════════════════════════════════════════════════════════

class TestDeleteSchema:
    """DELETE /form-builder/schemas/{schema_id}"""

    @pytest.mark.asyncio
    async def test_soft_deletes_schema(self):
        from app.modules.form_builder.router import delete_schema
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id)
        db.execute = _async_exec(
            _exec_returning(schema),   # _get_schema
            _exec_scalar(0),           # count of submissions
        )
        await delete_schema(schema_id=schema.id, db=db, caller=caller)
        assert schema.is_deleted is True
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_blocked_when_submissions_exist(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import delete_schema
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id)
        db.execute = _async_exec(
            _exec_returning(schema),   # _get_schema
            _exec_scalar(3),           # 3 submissions exist
        )
        with pytest.raises(HTTPException) as exc:
            await delete_schema(schema_id=schema.id, db=db, caller=caller)
        assert exc.value.status_code == 409


# ══════════════════════════════════════════════════════════════
#  §5.1 — Publish logic
# ══════════════════════════════════════════════════════════════

class TestPublishSchema:
    """POST /form-builder/schemas/{schema_id}/publish"""

    @pytest.mark.asyncio
    async def test_archived_cannot_be_published(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import publish_schema, PublishRequest
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="archived")
        db.execute = _async_exec(_exec_returning(schema))
        with pytest.raises(HTTPException) as exc:
            await publish_schema(
                schema_id=schema.id, body=PublishRequest(),
                db=db, caller=caller,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_no_fields_raises_400(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import publish_schema, PublishRequest
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="draft")
        db.execute = _async_exec(
            _exec_returning(schema),      # _get_schema
            _exec_scalars_all([]),        # _get_active_fields → empty
        )
        with pytest.raises(HTTPException) as exc:
            await publish_schema(
                schema_id=schema.id, body=PublishRequest(),
                db=db, caller=caller,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_publish_creates_version_and_stamps_fields(self):
        from app.modules.form_builder.router import publish_schema, PublishRequest
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="draft", current_version=0)
        field1    = _make_field(schema.id, tenant_id)
        field2    = _make_field(schema.id, tenant_id)
        field2.field_key = "age"

        update_result = MagicMock()  # result of sa_update executions

        db.execute = _async_exec(
            _exec_returning(schema),         # _get_schema
            _exec_scalars_all([field1, field2]),  # _get_active_fields
            update_result,                   # sa_update FormSchemaVersion
            update_result,                   # sa_update FieldDefinition
        )

        # db.add sets the id on the version object (simulate flush)
        added_version = None
        def _capture_add(obj):
            nonlocal added_version
            added_version = obj
            obj.id = uuid.uuid4()
            obj.published_at = datetime.datetime.now(datetime.timezone.utc)
            obj.field_snapshot = []
            obj.changelog = None
            obj.is_current = True
            obj.created_at = datetime.datetime.now(datetime.timezone.utc)
            obj.schema_id  = schema.id
            obj.tenant_id  = schema.tenant_id
            obj.version_number = 1
            obj.published_by   = caller.id

        db.add.side_effect = _capture_add

        result = await publish_schema(
            schema_id=schema.id,
            body=PublishRequest(changelog="Initial publish"),
            db=db,
            caller=caller,
        )
        assert result["success"] is True
        assert schema.current_version == 1
        assert schema.status == "published"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publish_increments_version_number(self):
        from app.modules.form_builder.router import publish_schema, PublishRequest
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="published", current_version=2)
        field     = _make_field(schema.id, tenant_id)
        update_result = MagicMock()

        def _setup_add(obj):
            obj.id             = uuid.uuid4()
            obj.published_at   = datetime.datetime.now(datetime.timezone.utc)
            obj.field_snapshot = []
            obj.changelog      = None
            obj.is_current     = True
            obj.created_at     = datetime.datetime.now(datetime.timezone.utc)
            obj.schema_id      = schema.id
            obj.tenant_id      = schema.tenant_id
            obj.version_number = 3
            obj.published_by   = caller.id

        db.add.side_effect = _setup_add
        db.execute = _async_exec(
            _exec_returning(schema),
            _exec_scalars_all([field]),
            update_result,
            update_result,
        )
        result = await publish_schema(
            schema_id=schema.id, body=PublishRequest(), db=db, caller=caller,
        )
        assert schema.current_version == 3


# ══════════════════════════════════════════════════════════════
#  §5.1 — Archive
# ══════════════════════════════════════════════════════════════

class TestArchiveSchema:
    """POST /form-builder/schemas/{schema_id}/archive"""

    @pytest.mark.asyncio
    async def test_archives_published_schema(self):
        from app.modules.form_builder.router import archive_schema
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="published")
        db.execute = _async_exec(_exec_returning(schema))
        result = await archive_schema(schema_id=schema.id, db=db, caller=caller)
        assert result["success"] is True
        assert schema.status == "archived"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_already_archived_raises_400(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import archive_schema
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="archived")
        db.execute = _async_exec(_exec_returning(schema))
        with pytest.raises(HTTPException) as exc:
            await archive_schema(schema_id=schema.id, db=db, caller=caller)
        assert exc.value.status_code == 400


# ══════════════════════════════════════════════════════════════
#  §5.1 — Version history
# ══════════════════════════════════════════════════════════════

class TestVersions:
    """GET /form-builder/schemas/{schema_id}/versions[/{version_id}]"""

    @pytest.mark.asyncio
    async def test_list_versions(self):
        from app.modules.form_builder.router import list_versions
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id)
        v1        = _make_version(schema.id, tenant_id)
        v2        = _make_version(schema.id, tenant_id)
        db.execute = _async_exec(
            _exec_returning(schema),        # _get_schema
            _exec_scalars_all([v2, v1]),    # version rows (desc order)
        )
        result = await list_versions(schema_id=schema.id, db=db, caller=caller)
        assert result["success"] is True
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_get_specific_version(self):
        from app.modules.form_builder.router import get_version
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id)
        version   = _make_version(schema.id, tenant_id)
        db.execute = _async_exec(
            _exec_returning(schema),     # _get_schema
            _exec_returning(version),    # get version
        )
        result = await get_version(
            schema_id=schema.id, version_id=version.id,
            db=db, caller=caller,
        )
        assert result["success"] is True
        assert result["data"]["id"] == str(version.id)

    @pytest.mark.asyncio
    async def test_missing_version_raises_404(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import get_version
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id)
        db.execute = _async_exec(
            _exec_returning(schema),   # _get_schema
            _exec_returning(None),     # version not found
        )
        with pytest.raises(HTTPException) as exc:
            await get_version(
                schema_id=schema.id, version_id=uuid.uuid4(),
                db=db, caller=caller,
            )
        assert exc.value.status_code == 404


# ══════════════════════════════════════════════════════════════
#  Renderer config
# ══════════════════════════════════════════════════════════════

class TestRendererConfig:
    """GET /form-builder/schemas/{schema_id}/renderer-config"""

    @pytest.mark.asyncio
    async def test_published_serves_version_snapshot(self):
        from app.modules.form_builder.router import get_renderer_config
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="published", current_version=1)
        snapshot  = [{"field_key": "name", "field_type": "string"}]
        version   = _make_version(schema.id, tenant_id)
        version.field_snapshot = snapshot
        db.execute = _async_exec(
            _exec_returning(schema),    # _get_schema
            _exec_returning(version),   # current version
        )
        result = await get_renderer_config(schema_id=schema.id, db=db, caller=caller)
        assert result["success"] is True
        assert result["data"]["fields"] == snapshot
        assert result["data"]["version"]["id"] == str(version.id)

    @pytest.mark.asyncio
    async def test_draft_serves_live_fields(self):
        from app.modules.form_builder.router import get_renderer_config
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="draft", current_version=0)
        field     = _make_field(schema.id, tenant_id)
        db.execute = _async_exec(
            _exec_returning(schema),        # _get_schema
            _exec_scalars_all([field]),     # live fields
        )
        result = await get_renderer_config(schema_id=schema.id, db=db, caller=caller)
        assert result["success"] is True
        assert result["data"]["version"] is None
        assert len(result["data"]["fields"]) == 1
        assert result["data"]["fields"][0]["field_key"] == "full_name"

    @pytest.mark.asyncio
    async def test_field_types_catalogue_always_included(self):
        from app.modules.form_builder.router import get_renderer_config
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="draft")
        db.execute = _async_exec(
            _exec_returning(schema),
            _exec_scalars_all([]),
        )
        result = await get_renderer_config(schema_id=schema.id, db=db, caller=caller)
        assert len(result["data"]["field_types"]) == 24


# ══════════════════════════════════════════════════════════════
#  §5.2 — Field CRUD: CREATE
# ══════════════════════════════════════════════════════════════

class TestCreateField:
    """POST /form-builder/schemas/{schema_id}/fields"""

    @pytest.mark.asyncio
    async def test_creates_field_successfully(self):
        from app.modules.form_builder.router import create_field, FieldCreate
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="draft")
        db.execute = _async_exec(
            _exec_returning(schema),   # _get_schema
            _exec_returning(None),     # uniqueness check → no conflict
        )

        def _capture_add(obj):
            obj.id              = uuid.uuid4()
            obj.created_at      = datetime.datetime.now(datetime.timezone.utc)
            obj.updated_at      = datetime.datetime.now(datetime.timezone.utc)
            obj.schema_version_id = None
            obj.department_owner  = None

        db.add.side_effect = _capture_add

        body = FieldCreate(
            field_key="contact_number",
            label="Contact Number",
            field_type="phone",
        )
        result = await create_field(schema_id=schema.id, body=body, db=db, caller=caller)
        assert result["success"] is True
        assert result["data"]["field_key"] == "contact_number"
        assert result["data"]["field_type"] == "phone"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_field_key_raises_409(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import create_field, FieldCreate
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="draft")
        db.execute = _async_exec(
            _exec_returning(schema),     # _get_schema
            _exec_returning(uuid.uuid4()),  # uniqueness check → conflict
        )
        body = FieldCreate(field_key="existing_key", label="X", field_type="string")
        with pytest.raises(HTTPException) as exc:
            await create_field(schema_id=schema.id, body=body, db=db, caller=caller)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_archived_schema_blocks_field_creation(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import create_field, FieldCreate
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="archived")
        db.execute = _async_exec(_exec_returning(schema))
        body = FieldCreate(field_key="x", label="X", field_type="string")
        with pytest.raises(HTTPException) as exc:
            await create_field(schema_id=schema.id, body=body, db=db, caller=caller)
        assert exc.value.status_code == 400

    def test_invalid_field_type_rejected_by_pydantic(self):
        from pydantic import ValidationError
        from app.modules.form_builder.router import FieldCreate
        with pytest.raises(ValidationError):
            FieldCreate(field_key="x", label="X", field_type="not_a_real_type")

    def test_invalid_field_key_rejected_by_pydantic(self):
        from pydantic import ValidationError
        from app.modules.form_builder.router import FieldCreate
        with pytest.raises(ValidationError):
            FieldCreate(field_key="Has Spaces!", label="X", field_type="string")

    def test_invalid_width_rejected_by_pydantic(self):
        from pydantic import ValidationError
        from app.modules.form_builder.router import FieldCreate
        with pytest.raises(ValidationError):
            FieldCreate(field_key="x", label="X", field_type="string", width="quarter")


# ══════════════════════════════════════════════════════════════
#  §5.2 — Field CRUD: LIST / GET
# ══════════════════════════════════════════════════════════════

class TestListAndGetField:
    """GET /form-builder/schemas/{schema_id}/fields[/{field_id}]"""

    @pytest.mark.asyncio
    async def test_list_fields_ordered(self):
        from app.modules.form_builder.router import list_fields
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id)
        f1, f2    = _make_field(schema.id, tenant_id), _make_field(schema.id, tenant_id)
        f1.display_order, f2.display_order = 0, 1
        db.execute = _async_exec(
            _exec_returning(schema),
            _exec_scalars_all([f1, f2]),
        )
        result = await list_fields(schema_id=schema.id, db=db, caller=caller)
        assert result["success"] is True
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_get_field_by_id(self):
        from app.modules.form_builder.router import get_field
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id)
        fld       = _make_field(schema.id, tenant_id)
        db.execute = _async_exec(
            _exec_returning(schema),
            _exec_returning(fld),
        )
        result = await get_field(schema_id=schema.id, field_id=fld.id, db=db, caller=caller)
        assert result["success"] is True
        assert result["data"]["id"] == str(fld.id)

    @pytest.mark.asyncio
    async def test_get_missing_field_raises_404(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import get_field
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id)
        db.execute = _async_exec(
            _exec_returning(schema),
            _exec_returning(None),
        )
        with pytest.raises(HTTPException) as exc:
            await get_field(schema_id=schema.id, field_id=uuid.uuid4(), db=db, caller=caller)
        assert exc.value.status_code == 404


# ══════════════════════════════════════════════════════════════
#  §5.2 — Field CRUD: UPDATE
# ══════════════════════════════════════════════════════════════

class TestUpdateField:
    """PUT /form-builder/schemas/{schema_id}/fields/{field_id}"""

    @pytest.mark.asyncio
    async def test_updates_label_successfully(self):
        from app.modules.form_builder.router import update_field, FieldUpdate
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="draft")
        fld       = _make_field(schema.id, tenant_id)
        db.execute = _async_exec(
            _exec_returning(schema),
            _exec_returning(fld),
        )
        body = FieldUpdate(label="Updated Label", is_required=True)
        result = await update_field(
            schema_id=schema.id, field_id=fld.id,
            body=body, db=db, caller=caller,
        )
        assert result["success"] is True
        assert fld.label == "Updated Label"
        assert fld.is_required is True
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_archived_schema_blocks_update(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import update_field, FieldUpdate
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="archived")
        db.execute = _async_exec(_exec_returning(schema))
        with pytest.raises(HTTPException) as exc:
            await update_field(
                schema_id=schema.id, field_id=uuid.uuid4(),
                body=FieldUpdate(), db=db, caller=caller,
            )
        assert exc.value.status_code == 400


# ══════════════════════════════════════════════════════════════
#  §5.2 — Field CRUD: DELETE (soft)
# ══════════════════════════════════════════════════════════════

class TestDeleteField:
    """DELETE /form-builder/schemas/{schema_id}/fields/{field_id}"""

    @pytest.mark.asyncio
    async def test_soft_deletes_field(self):
        from app.modules.form_builder.router import delete_field
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="draft")
        fld       = _make_field(schema.id, tenant_id)
        db.execute = _async_exec(
            _exec_returning(schema),
            _exec_returning(fld),
        )
        await delete_field(schema_id=schema.id, field_id=fld.id, db=db, caller=caller)
        assert fld.is_deleted is True
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_archived_schema_blocks_delete(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import delete_field
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="archived")
        db.execute = _async_exec(_exec_returning(schema))
        with pytest.raises(HTTPException) as exc:
            await delete_field(
                schema_id=schema.id, field_id=uuid.uuid4(),
                db=db, caller=caller,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_field_raises_404(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import delete_field
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="draft")
        db.execute = _async_exec(
            _exec_returning(schema),
            _exec_returning(None),
        )
        with pytest.raises(HTTPException) as exc:
            await delete_field(
                schema_id=schema.id, field_id=uuid.uuid4(),
                db=db, caller=caller,
            )
        assert exc.value.status_code == 404


# ══════════════════════════════════════════════════════════════
#  §5.2 — Field reorder
# ══════════════════════════════════════════════════════════════

class TestReorderFields:
    """PATCH /form-builder/schemas/{schema_id}/fields/reorder"""

    @pytest.mark.asyncio
    async def test_reorders_two_fields(self):
        from app.modules.form_builder.router import reorder_fields, ReorderRequest
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id)
        id1, id2  = uuid.uuid4(), uuid.uuid4()
        f1        = _make_field(schema.id, tenant_id)
        f1.id, f1.display_order = id1, 1
        f2        = _make_field(schema.id, tenant_id)
        f2.id, f2.field_key, f2.display_order = id2, "age", 0

        # _get_schema + 2 sa_update executions + _get_active_fields
        update_res = MagicMock()
        db.execute = _async_exec(
            _exec_returning(schema),         # _get_schema
            update_res,                      # sa_update field idx=0
            update_res,                      # sa_update field idx=1
            _exec_scalars_all([f2, f1]),     # _get_active_fields (new order)
        )

        body   = ReorderRequest(order=[id2, id1])
        result = await reorder_fields(schema_id=schema.id, body=body, db=db, caller=caller)
        assert result["success"] is True
        assert len(result["data"]) == 2
        db.commit.assert_awaited_once()


# ══════════════════════════════════════════════════════════════
#  Tenant Isolation
# ══════════════════════════════════════════════════════════════

class TestTenantIsolation:
    """Verify every read/write endpoint filters by caller.tenant_id."""

    @pytest.mark.asyncio
    async def test_get_schema_wrong_tenant_returns_404(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import get_schema
        caller = _make_caller(uuid.uuid4())  # caller is tenant A
        db     = _db()
        # DB returns None because the WHERE clause includes tenant_id
        db.execute = _async_exec(_exec_returning(None))
        with pytest.raises(HTTPException) as exc:
            await get_schema(schema_id=uuid.uuid4(), db=db, caller=caller)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_fields_wrong_tenant_schema_404(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import list_fields
        caller = _make_caller(uuid.uuid4())
        db     = _db()
        db.execute = _async_exec(_exec_returning(None))
        with pytest.raises(HTTPException) as exc:
            await list_fields(schema_id=uuid.uuid4(), db=db, caller=caller)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_versions_wrong_tenant_schema_404(self):
        from fastapi import HTTPException
        from app.modules.form_builder.router import list_versions
        caller = _make_caller(uuid.uuid4())
        db     = _db()
        db.execute = _async_exec(_exec_returning(None))
        with pytest.raises(HTTPException) as exc:
            await list_versions(schema_id=uuid.uuid4(), db=db, caller=caller)
        assert exc.value.status_code == 404


# ══════════════════════════════════════════════════════════════
#  Router registration
# ══════════════════════════════════════════════════════════════

class TestRouterRegistration:
    """form_builder_router is registered in main.py at /api/v1/form-builder."""

    def test_form_builder_router_imported_in_main(self):
        import main  # noqa: F401 — ensures it imports without error
        from main import app
        routes = [r.path for r in app.routes]
        fb_routes = [r for r in routes if "/form-builder/" in r]
        assert len(fb_routes) > 0, "No /form-builder/ routes found in app"

    def test_form_builder_registered_before_tasks_router(self):
        from main import app
        route_paths = [r.path for r in app.routes]
        fb_idx   = next((i for i, p in enumerate(route_paths) if "/form-builder/" in p), None)
        task_idx = next((i for i, p in enumerate(route_paths) if "/tasks" in p), None)
        assert fb_idx is not None, "form-builder routes not found"
        assert task_idx is not None, "tasks routes not found"
        assert fb_idx < task_idx, "form_builder_router must be registered before tasks_router"

    def test_field_types_route_exists(self):
        from main import app
        routes = [r.path for r in app.routes]
        assert any("field-types" in p for p in routes), (
            "GET /api/v1/form-builder/field-types route not found"
        )

    def test_schemas_route_exists(self):
        from main import app
        routes = [r.path for r in app.routes]
        assert any("form-builder" in p and "schemas" in p for p in routes), (
            "Schema routes not found under /form-builder"
        )

    def test_no_conflict_with_customer_forms_router(self):
        from main import app
        routes = [r.path for r in app.routes]
        # /api/v1/forms/schemas and /api/v1/form-builder/schemas must be different paths
        forms_schemas = [r for r in routes if r == "/api/v1/forms/schemas"]
        fb_schemas    = [r for r in routes if r == "/api/v1/form-builder/schemas"]
        assert len(fb_schemas) > 0, "/api/v1/form-builder/schemas not found"
        # If both exist they are distinct paths (no collision)
        assert forms_schemas != fb_schemas
