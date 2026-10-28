# ============================================================
# FORM BUILDER SUBMISSION ROUTER — UNIT TESTS
# tests/form_builder/test_submission_router.py
#
# Tests every route handler in submission_router.py via direct
# function calls (no HTTP client, no running DB).
#
# Coverage:
#   Association CRUD — create, list, get, update, soft-delete
#   Context lookup  — schemas for a given context
#   Validate dry-run — valid, invalid, empty schema
#   Save draft     — new draft, update existing, type errors blocked
#   List submissions — filters, pagination
#   Submit form    — valid (published), invalid (validation errors),
#                    draft schema blocked, empty snapshot
#   Get submission  — found, 404, wrong tenant
#   Approve        — success, already-approved blocked, not-submitted blocked
#   Reject         — success, already-rejected blocked
#   Export         — JSON download, 404
#   Router registration — both routers merged at /form-builder
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
from unittest.mock import AsyncMock, MagicMock


# ── Mock factories ────────────────────────────────────────────

def _make_caller(tenant_id: uuid.UUID | None = None, role_name: str = "admin") -> MagicMock:
    c = MagicMock()
    c.id        = uuid.uuid4()
    c.tenant_id = tenant_id or uuid.uuid4()
    c.role      = MagicMock(name=role_name, level=5)
    return c


def _make_schema(tenant_id: uuid.UUID, status: str = "published", cv: int = 1) -> MagicMock:
    s = MagicMock()
    s.id              = uuid.uuid4()
    s.tenant_id       = tenant_id
    s.name            = "Test Form"
    s.machine_name    = "test_form"
    s.description     = None
    s.module          = "customer"
    s.status          = status
    s.current_version = cv
    s.icon            = None
    s.color           = None
    s.created_by      = uuid.uuid4()
    s.is_deleted      = False
    s.created_at      = datetime.datetime.now(datetime.timezone.utc)
    s.updated_at      = datetime.datetime.now(datetime.timezone.utc)
    return s


def _make_version(schema_id: uuid.UUID, tenant_id: uuid.UUID, snapshot: list | None = None) -> MagicMock:
    v = MagicMock()
    v.id             = uuid.uuid4()
    v.schema_id      = schema_id
    v.tenant_id      = tenant_id
    v.version_number = 1
    v.published_at   = datetime.datetime.now(datetime.timezone.utc)
    v.published_by   = uuid.uuid4()
    v.field_snapshot = snapshot or []
    v.changelog      = None
    v.is_current     = True
    v.created_at     = datetime.datetime.now(datetime.timezone.utc)
    return v


def _make_association(tenant_id: uuid.UUID, schema_id: uuid.UUID | None = None) -> MagicMock:
    a = MagicMock()
    a.id                  = uuid.uuid4()
    a.tenant_id           = tenant_id
    a.schema_id           = schema_id or uuid.uuid4()
    a.schema_version_id   = None
    a.context_type        = "module"
    a.context_id          = uuid.uuid4()
    a.context_label       = "Customer Module"
    a.is_mandatory        = False
    a.display_order       = 0
    a.trigger_event       = None
    a.auto_populate_fields = None
    a.created_by          = uuid.uuid4()
    a.is_deleted          = False
    a.created_at          = datetime.datetime.now(datetime.timezone.utc)
    a.updated_at          = datetime.datetime.now(datetime.timezone.utc)
    return a


def _make_submission(tenant_id: uuid.UUID, schema_id: uuid.UUID, status: str = "submitted") -> MagicMock:
    s = MagicMock()
    s.id                = uuid.uuid4()
    s.tenant_id         = tenant_id
    s.schema_id         = schema_id
    s.schema_version_id = uuid.uuid4()
    s.entity_type       = "customer"
    s.entity_id         = uuid.uuid4()
    s.association_id    = None
    s.submitted_by      = uuid.uuid4()
    s.submitted_at      = datetime.datetime.now(datetime.timezone.utc)
    s.status            = status
    s.data              = {"full_name": "Alice"}
    s.draft_data        = None
    s.approved_by       = None
    s.approved_at       = None
    s.rejection_reason  = None
    s.is_deleted        = False
    s.created_by        = uuid.uuid4()
    s.created_at        = datetime.datetime.now(datetime.timezone.utc)
    s.updated_at        = datetime.datetime.now(datetime.timezone.utc)
    return s


def _exec_returning(value) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _exec_scalar(value) -> MagicMock:
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _exec_scalars_all(rows: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = rows
    return r


def _exec_all(rows: list) -> MagicMock:
    r = MagicMock()
    r.all.return_value = rows
    return r


def _async_exec(*side_effects) -> AsyncMock:
    return AsyncMock(side_effect=list(side_effects))


def _db() -> AsyncMock:
    db = AsyncMock()
    db.add    = MagicMock()
    db.flush  = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ── Minimal snapshot for validation ──────────────────────────

def _string_field_snapshot(key: str = "full_name", required: bool = False) -> dict:
    return {
        "field_key":         key,
        "label":             "Full Name",
        "field_type":        "string",
        "is_required":       required,
        "is_unique":         False,
        "is_readonly":       False,
        "is_hidden":         False,
        "default_value":     None,
        "validation_rules":  {},
        "options":           None,
        "conditional_logic": None,
        "role_visibility":   None,
        "role_editable":     None,
        "stage_visible_from": None,
        "stage_required_at":  None,
    }


# ══════════════════════════════════════════════════════════════
#  Association CRUD
# ══════════════════════════════════════════════════════════════

class TestCreateAssociation:
    """POST /form-builder/associations"""

    @pytest.mark.asyncio
    async def test_creates_association_successfully(self):
        from app.modules.form_builder.submission_router import (
            create_association, AssociationCreate,
        )
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id)
        db.execute = _async_exec(_exec_returning(schema))

        def _capture_add(obj):
            obj.id          = uuid.uuid4()
            obj.created_at  = datetime.datetime.now(datetime.timezone.utc)
            obj.updated_at  = datetime.datetime.now(datetime.timezone.utc)
            obj.schema_version_id   = None
            obj.auto_populate_fields = None

        db.add.side_effect = _capture_add

        body = AssociationCreate(
            schema_id     = schema.id,
            context_type  = "module",
            context_label = "Customer",
        )
        result = await create_association(body=body, db=db, caller=caller)
        assert result["success"] is True
        assert result["data"]["context_type"] == "module"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_archived_schema_blocked(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import (
            create_association, AssociationCreate,
        )
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="archived")
        db.execute = _async_exec(_exec_returning(schema))
        body = AssociationCreate(
            schema_id=schema.id, context_type="module", context_label="X",
        )
        with pytest.raises(HTTPException) as exc:
            await create_association(body=body, db=db, caller=caller)
        assert exc.value.status_code == 400

    def test_invalid_context_type_rejected_by_pydantic(self):
        from pydantic import ValidationError
        from app.modules.form_builder.submission_router import AssociationCreate
        with pytest.raises(ValidationError):
            AssociationCreate(
                schema_id=uuid.uuid4(),
                context_type="invalid_type",
                context_label="X",
            )

    def test_invalid_trigger_event_rejected_by_pydantic(self):
        from pydantic import ValidationError
        from app.modules.form_builder.submission_router import AssociationCreate
        with pytest.raises(ValidationError):
            AssociationCreate(
                schema_id=uuid.uuid4(),
                context_type="module",
                context_label="X",
                trigger_event="bad_event",
            )


class TestListAssociations:
    """GET /form-builder/associations"""

    @pytest.mark.asyncio
    async def test_returns_paginated_associations(self):
        from app.modules.form_builder.submission_router import list_associations
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        a1        = _make_association(tenant_id)
        db.execute = _async_exec(_exec_scalar(1), _exec_scalars_all([a1]))
        result = await list_associations(
            schema_id=None, context_type=None, page=1, limit=20,
            db=db, caller=caller,
        )
        assert result["success"] is True
        assert result["total"] == 1
        assert len(result["data"]) == 1

    @pytest.mark.asyncio
    async def test_invalid_context_type_raises_400(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import list_associations
        caller = _make_caller()
        db     = _db()
        with pytest.raises(HTTPException) as exc:
            await list_associations(
                schema_id=None, context_type="bad_type", page=1, limit=20,
                db=db, caller=caller,
            )
        assert exc.value.status_code == 400


class TestGetAssociation:
    """GET /form-builder/associations/{id}"""

    @pytest.mark.asyncio
    async def test_returns_association(self):
        from app.modules.form_builder.submission_router import get_association
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        assoc     = _make_association(tenant_id)
        db.execute = _async_exec(_exec_returning(assoc))
        result = await get_association(association_id=assoc.id, db=db, caller=caller)
        assert result["success"] is True
        assert result["data"]["id"] == str(assoc.id)

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import get_association
        caller = _make_caller()
        db     = _db()
        db.execute = _async_exec(_exec_returning(None))
        with pytest.raises(HTTPException) as exc:
            await get_association(association_id=uuid.uuid4(), db=db, caller=caller)
        assert exc.value.status_code == 404


class TestUpdateAssociation:
    """PUT /form-builder/associations/{id}"""

    @pytest.mark.asyncio
    async def test_updates_label(self):
        from app.modules.form_builder.submission_router import update_association, AssociationUpdate
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        assoc     = _make_association(tenant_id)
        db.execute = _async_exec(_exec_returning(assoc))
        body = AssociationUpdate(context_label="New Label", is_mandatory=True)
        result = await update_association(
            association_id=assoc.id, body=body, db=db, caller=caller,
        )
        assert result["success"] is True
        assert assoc.context_label == "New Label"
        assert assoc.is_mandatory is True
        db.commit.assert_awaited_once()


class TestDeleteAssociation:
    """DELETE /form-builder/associations/{id}"""

    @pytest.mark.asyncio
    async def test_soft_deletes(self):
        from app.modules.form_builder.submission_router import delete_association
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        assoc     = _make_association(tenant_id)
        db.execute = _async_exec(_exec_returning(assoc))
        await delete_association(association_id=assoc.id, db=db, caller=caller)
        assert assoc.is_deleted is True
        db.commit.assert_awaited_once()


# ══════════════════════════════════════════════════════════════
#  Context lookup
# ══════════════════════════════════════════════════════════════

class TestContextLookup:
    """GET /form-builder/context/{context_type}/{context_id}/schemas"""

    @pytest.mark.asyncio
    async def test_returns_published_schemas(self):
        from app.modules.form_builder.submission_router import get_schemas_for_context
        tenant_id  = uuid.uuid4()
        caller     = _make_caller(tenant_id)
        db         = _db()
        schema     = _make_schema(tenant_id)
        assoc      = _make_association(tenant_id, schema.id)
        db.execute = _async_exec(_exec_all([(assoc, schema)]))
        result = await get_schemas_for_context(
            context_type="module",
            context_id=assoc.context_id,
            db=db,
            caller=caller,
        )
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["schema"]["id"] == str(schema.id)

    @pytest.mark.asyncio
    async def test_invalid_context_type_raises_400(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import get_schemas_for_context
        caller = _make_caller()
        db     = _db()
        with pytest.raises(HTTPException) as exc:
            await get_schemas_for_context(
                context_type="bad_type",
                context_id=uuid.uuid4(),
                db=db,
                caller=caller,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_result(self):
        from app.modules.form_builder.submission_router import get_schemas_for_context
        caller = _make_caller()
        db     = _db()
        db.execute = _async_exec(_exec_all([]))
        result = await get_schemas_for_context(
            context_type="module",
            context_id=uuid.uuid4(),
            db=db,
            caller=caller,
        )
        assert result["data"] == []


# ══════════════════════════════════════════════════════════════
#  Validate dry-run
# ══════════════════════════════════════════════════════════════

class TestValidateDryRun:
    """POST /form-builder/submissions/validate"""

    @pytest.mark.asyncio
    async def test_valid_data_returns_is_valid_true(self):
        from unittest.mock import patch
        from app.modules.form_builder.submission_router import (
            validate_submission_dry_run, ValidateRequest,
        )
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="published")
        snapshot  = [_string_field_snapshot("full_name", required=False)]
        version   = _make_version(schema.id, tenant_id, snapshot=snapshot)
        db.execute = _async_exec(
            _exec_returning(schema),    # _load_schema
            _exec_returning(version),   # _snapshot_for_validation (published)
        )
        body = ValidateRequest(schema_id=schema.id, data={"full_name": "Alice"})
        result = await validate_submission_dry_run(body=body, db=db, caller=caller)
        assert result["success"] is True
        assert result["data"]["is_valid"] is True
        assert result["data"]["errors"] == []

    @pytest.mark.asyncio
    async def test_type_error_returns_is_valid_false(self):
        from app.modules.form_builder.submission_router import (
            validate_submission_dry_run, ValidateRequest,
        )
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="published")
        # integer field with string value that can't coerce
        snapshot  = [{
            **_string_field_snapshot("age"),
            "field_type": "integer",
            "label": "Age",
        }]
        version   = _make_version(schema.id, tenant_id, snapshot=snapshot)
        db.execute = _async_exec(
            _exec_returning(schema),
            _exec_returning(version),
        )
        body = ValidateRequest(schema_id=schema.id, data={"age": "not_a_number"})
        result = await validate_submission_dry_run(body=body, db=db, caller=caller)
        assert result["success"] is True
        assert result["data"]["is_valid"] is False
        assert any(e["error_code"] == "type_error" for e in result["data"]["errors"])

    @pytest.mark.asyncio
    async def test_empty_snapshot_raises_400(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import (
            validate_submission_dry_run, ValidateRequest,
        )
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="published")
        version   = _make_version(schema.id, tenant_id, snapshot=[])
        db.execute = _async_exec(
            _exec_returning(schema),
            _exec_returning(version),
        )
        with pytest.raises(HTTPException) as exc:
            await validate_submission_dry_run(
                body=ValidateRequest(schema_id=schema.id, data={}),
                db=db, caller=caller,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_required_field_missing_caught_in_non_draft_mode(self):
        from app.modules.form_builder.submission_router import (
            validate_submission_dry_run, ValidateRequest,
        )
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="published")
        snapshot  = [_string_field_snapshot("full_name", required=True)]
        version   = _make_version(schema.id, tenant_id, snapshot=snapshot)
        db.execute = _async_exec(_exec_returning(schema), _exec_returning(version))
        # Submitting empty data with is_draft=False triggers required check
        body = ValidateRequest(schema_id=schema.id, data={}, is_draft=False)
        result = await validate_submission_dry_run(body=body, db=db, caller=caller)
        assert result["data"]["is_valid"] is False
        assert "full_name" in result["data"]["missing_required_fields"]

    @pytest.mark.asyncio
    async def test_required_field_skipped_in_draft_mode(self):
        from app.modules.form_builder.submission_router import (
            validate_submission_dry_run, ValidateRequest,
        )
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="published")
        snapshot  = [_string_field_snapshot("full_name", required=True)]
        version   = _make_version(schema.id, tenant_id, snapshot=snapshot)
        db.execute = _async_exec(_exec_returning(schema), _exec_returning(version))
        # is_draft=True skips required checks
        body = ValidateRequest(schema_id=schema.id, data={}, is_draft=True)
        result = await validate_submission_dry_run(body=body, db=db, caller=caller)
        assert result["data"]["is_valid"] is True


# ══════════════════════════════════════════════════════════════
#  Draft save
# ══════════════════════════════════════════════════════════════

class TestSaveDraft:
    """POST /form-builder/submissions/draft"""

    @pytest.mark.asyncio
    async def test_creates_new_draft(self):
        from app.modules.form_builder.submission_router import (
            save_draft_submission, DraftSaveRequest,
        )
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="published")
        snapshot  = [_string_field_snapshot("full_name")]
        version   = _make_version(schema.id, tenant_id, snapshot=snapshot)
        db.execute = _async_exec(
            _exec_returning(schema),    # _load_schema
            _exec_returning(version),   # _snapshot_for_validation
        )

        def _capture_add(obj):
            obj.id          = uuid.uuid4()
            obj.submitted_at = datetime.datetime.now(datetime.timezone.utc)
            obj.created_at   = datetime.datetime.now(datetime.timezone.utc)
            obj.updated_at   = datetime.datetime.now(datetime.timezone.utc)
            obj.approved_by  = None
            obj.approved_at  = None
            obj.rejection_reason = None

        db.add.side_effect = _capture_add

        body = DraftSaveRequest(
            schema_id=schema.id,
            entity_type="customer",
            data={"full_name": "Bob"},
        )
        result = await save_draft_submission(body=body, db=db, caller=caller)
        assert result["success"] is True
        assert result["data"]["status"] == "draft"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_existing_draft(self):
        from app.modules.form_builder.submission_router import (
            save_draft_submission, DraftSaveRequest,
        )
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="published")
        snapshot  = [_string_field_snapshot("full_name")]
        version   = _make_version(schema.id, tenant_id, snapshot=snapshot)
        existing_draft = _make_submission(tenant_id, schema.id, status="draft")
        existing_draft.draft_data = {}

        db.execute = _async_exec(
            _exec_returning(schema),        # _load_schema
            _exec_returning(version),       # _snapshot_for_validation
            _exec_returning(existing_draft),# existing draft lookup
        )
        body = DraftSaveRequest(
            schema_id=schema.id,
            entity_type="customer",
            data={"full_name": "Updated"},
            draft_id=existing_draft.id,
        )
        result = await save_draft_submission(body=body, db=db, caller=caller)
        assert result["success"] is True
        # draft_data should be updated (set by validation engine coerce)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_type_error_raises_422(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import (
            save_draft_submission, DraftSaveRequest,
        )
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="published")
        snapshot  = [{**_string_field_snapshot("age"), "field_type": "integer", "label": "Age"}]
        version   = _make_version(schema.id, tenant_id, snapshot=snapshot)
        db.execute = _async_exec(_exec_returning(schema), _exec_returning(version))

        body = DraftSaveRequest(
            schema_id=schema.id,
            entity_type="customer",
            data={"age": "not_a_number"},
        )
        with pytest.raises(HTTPException) as exc:
            await save_draft_submission(body=body, db=db, caller=caller)
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_archived_schema_blocked(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import (
            save_draft_submission, DraftSaveRequest,
        )
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="archived")
        db.execute = _async_exec(_exec_returning(schema))
        body = DraftSaveRequest(
            schema_id=schema.id, entity_type="customer", data={},
        )
        with pytest.raises(HTTPException) as exc:
            await save_draft_submission(body=body, db=db, caller=caller)
        assert exc.value.status_code == 400


# ══════════════════════════════════════════════════════════════
#  Submit form
# ══════════════════════════════════════════════════════════════

class TestSubmitForm:
    """POST /form-builder/submissions"""

    @pytest.mark.asyncio
    async def test_valid_submission_succeeds(self):
        from app.modules.form_builder.submission_router import submit_form, SubmitRequest
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="published")
        snapshot  = [_string_field_snapshot("full_name")]
        version   = _make_version(schema.id, tenant_id, snapshot=snapshot)
        db.execute = _async_exec(
            _exec_returning(schema),    # _load_schema
            _exec_returning(version),   # _load_current_version
        )

        def _capture_add(obj):
            obj.id           = uuid.uuid4()
            obj.submitted_at = datetime.datetime.now(datetime.timezone.utc)
            obj.created_at   = datetime.datetime.now(datetime.timezone.utc)
            obj.updated_at   = datetime.datetime.now(datetime.timezone.utc)
            obj.draft_data   = None
            obj.approved_by  = None
            obj.approved_at  = None
            obj.rejection_reason = None

        db.add.side_effect = _capture_add

        body = SubmitRequest(
            schema_id=schema.id,
            entity_type="customer",
            data={"full_name": "Alice"},
        )
        result = await submit_form(body=body, db=db, caller=caller)
        assert result["success"] is True
        assert result["data"]["status"] == "submitted"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_draft_schema_blocked(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import submit_form, SubmitRequest
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="draft")
        db.execute = _async_exec(_exec_returning(schema))
        body = SubmitRequest(
            schema_id=schema.id, entity_type="customer", data={},
        )
        with pytest.raises(HTTPException) as exc:
            await submit_form(body=body, db=db, caller=caller)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_no_version_raises_400(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import submit_form, SubmitRequest
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="published")
        db.execute = _async_exec(
            _exec_returning(schema),
            _exec_returning(None),  # no version
        )
        body = SubmitRequest(
            schema_id=schema.id, entity_type="customer", data={},
        )
        with pytest.raises(HTTPException) as exc:
            await submit_form(body=body, db=db, caller=caller)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_validation_failure_raises_422(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import submit_form, SubmitRequest
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="published")
        # Required field — empty submission must fail
        snapshot  = [_string_field_snapshot("full_name", required=True)]
        version   = _make_version(schema.id, tenant_id, snapshot=snapshot)
        db.execute = _async_exec(_exec_returning(schema), _exec_returning(version))

        body = SubmitRequest(
            schema_id=schema.id, entity_type="customer", data={},
        )
        with pytest.raises(HTTPException) as exc:
            await submit_form(body=body, db=db, caller=caller)
        assert exc.value.status_code == 422
        assert "errors" in exc.value.detail

    @pytest.mark.asyncio
    async def test_data_coercion_applied_on_success(self):
        """Coerced data (not raw input) is stored."""
        from app.modules.form_builder.submission_router import submit_form, SubmitRequest
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id, status="published")
        # Integer field — "42" should coerce to 42
        snapshot  = [{**_string_field_snapshot("age"), "field_type": "integer", "label": "Age"}]
        version   = _make_version(schema.id, tenant_id, snapshot=snapshot)
        db.execute = _async_exec(_exec_returning(schema), _exec_returning(version))

        stored_data = {}

        def _capture_add(obj):
            obj.id           = uuid.uuid4()
            obj.submitted_at = datetime.datetime.now(datetime.timezone.utc)
            obj.created_at   = datetime.datetime.now(datetime.timezone.utc)
            obj.updated_at   = datetime.datetime.now(datetime.timezone.utc)
            obj.draft_data   = None
            obj.approved_by  = None
            obj.approved_at  = None
            obj.rejection_reason = None
            stored_data["data"] = obj.data

        db.add.side_effect = _capture_add

        body = SubmitRequest(
            schema_id=schema.id, entity_type="customer", data={"age": "42"},
        )
        await submit_form(body=body, db=db, caller=caller)
        # Coerced value should be integer 42, not string "42"
        assert stored_data["data"].get("age") == 42


# ══════════════════════════════════════════════════════════════
#  List submissions
# ══════════════════════════════════════════════════════════════

class TestListSubmissions:
    """GET /form-builder/submissions"""

    @pytest.mark.asyncio
    async def test_returns_paginated_results(self):
        from app.modules.form_builder.submission_router import list_submissions
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        schema    = _make_schema(tenant_id)
        s1        = _make_submission(tenant_id, schema.id)
        db.execute = _async_exec(_exec_scalar(1), _exec_scalars_all([s1]))
        result = await list_submissions(
            schema_id=None, entity_type=None, entity_id=None,
            sub_status=None, page=1, limit=20, db=db, caller=caller,
        )
        assert result["success"] is True
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_invalid_status_raises_400(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import list_submissions
        caller = _make_caller()
        db     = _db()
        with pytest.raises(HTTPException) as exc:
            await list_submissions(
                schema_id=None, entity_type=None, entity_id=None,
                sub_status="bad_status", page=1, limit=20, db=db, caller=caller,
            )
        assert exc.value.status_code == 400


# ══════════════════════════════════════════════════════════════
#  Get submission
# ══════════════════════════════════════════════════════════════

class TestGetSubmission:
    """GET /form-builder/submissions/{submission_id}"""

    @pytest.mark.asyncio
    async def test_returns_submission(self):
        from app.modules.form_builder.submission_router import get_submission
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        sub       = _make_submission(tenant_id, uuid.uuid4())
        db.execute = _async_exec(_exec_returning(sub))
        result = await get_submission(submission_id=sub.id, db=db, caller=caller)
        assert result["success"] is True
        assert result["data"]["id"] == str(sub.id)

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import get_submission
        caller = _make_caller()
        db     = _db()
        db.execute = _async_exec(_exec_returning(None))
        with pytest.raises(HTTPException) as exc:
            await get_submission(submission_id=uuid.uuid4(), db=db, caller=caller)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_wrong_tenant_returns_404(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import get_submission
        caller = _make_caller(uuid.uuid4())
        db     = _db()
        db.execute = _async_exec(_exec_returning(None))
        with pytest.raises(HTTPException) as exc:
            await get_submission(submission_id=uuid.uuid4(), db=db, caller=caller)
        assert exc.value.status_code == 404


# ══════════════════════════════════════════════════════════════
#  Approve / Reject
# ══════════════════════════════════════════════════════════════

class TestApproveSubmission:
    """PATCH /form-builder/submissions/{id}/approve"""

    @pytest.mark.asyncio
    async def test_approves_submitted(self):
        from app.modules.form_builder.submission_router import approve_submission
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        sub       = _make_submission(tenant_id, uuid.uuid4(), status="submitted")
        db.execute = _async_exec(_exec_returning(sub))
        result = await approve_submission(submission_id=sub.id, db=db, caller=caller)
        assert result["success"] is True
        assert sub.status == "approved"
        assert sub.approved_by == caller.id
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_already_approved_raises_400(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import approve_submission
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        sub       = _make_submission(tenant_id, uuid.uuid4(), status="approved")
        db.execute = _async_exec(_exec_returning(sub))
        with pytest.raises(HTTPException) as exc:
            await approve_submission(submission_id=sub.id, db=db, caller=caller)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_draft_cannot_be_approved(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import approve_submission
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        sub       = _make_submission(tenant_id, uuid.uuid4(), status="draft")
        db.execute = _async_exec(_exec_returning(sub))
        with pytest.raises(HTTPException) as exc:
            await approve_submission(submission_id=sub.id, db=db, caller=caller)
        assert exc.value.status_code == 400


class TestRejectSubmission:
    """PATCH /form-builder/submissions/{id}/reject"""

    @pytest.mark.asyncio
    async def test_rejects_submitted(self):
        from app.modules.form_builder.submission_router import reject_submission, RejectRequest
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        sub       = _make_submission(tenant_id, uuid.uuid4(), status="submitted")
        db.execute = _async_exec(_exec_returning(sub))
        result = await reject_submission(
            submission_id=sub.id,
            body=RejectRequest(reason="Incomplete data"),
            db=db, caller=caller,
        )
        assert result["success"] is True
        assert sub.status == "rejected"
        assert sub.rejection_reason == "Incomplete data"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_already_rejected_raises_400(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import reject_submission, RejectRequest
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        sub       = _make_submission(tenant_id, uuid.uuid4(), status="rejected")
        db.execute = _async_exec(_exec_returning(sub))
        with pytest.raises(HTTPException) as exc:
            await reject_submission(
                submission_id=sub.id,
                body=RejectRequest(reason="reason"),
                db=db, caller=caller,
            )
        assert exc.value.status_code == 400


# ══════════════════════════════════════════════════════════════
#  Export
# ══════════════════════════════════════════════════════════════

class TestExportSubmission:
    """GET /form-builder/submissions/{id}/export"""

    @pytest.mark.asyncio
    async def test_returns_json_streaming_response(self):
        from fastapi.responses import StreamingResponse
        from app.modules.form_builder.submission_router import export_submission
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        sub       = _make_submission(tenant_id, uuid.uuid4())
        db.execute = _async_exec(_exec_returning(sub))
        response = await export_submission(submission_id=sub.id, db=db, caller=caller)
        assert isinstance(response, StreamingResponse)
        assert "attachment" in response.headers["content-disposition"]
        assert str(sub.id) in response.headers["content-disposition"]

    @pytest.mark.asyncio
    async def test_missing_submission_raises_404(self):
        from fastapi import HTTPException
        from app.modules.form_builder.submission_router import export_submission
        caller = _make_caller()
        db     = _db()
        db.execute = _async_exec(_exec_returning(None))
        with pytest.raises(HTTPException) as exc:
            await export_submission(submission_id=uuid.uuid4(), db=db, caller=caller)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_export_content_is_valid_json(self):
        import json
        from app.modules.form_builder.submission_router import export_submission
        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        db        = _db()
        sub       = _make_submission(tenant_id, uuid.uuid4())
        sub.data  = {"full_name": "Alice", "age": 30}
        db.execute = _async_exec(_exec_returning(sub))
        response = await export_submission(submission_id=sub.id, db=db, caller=caller)
        # Read all bytes from the streaming response body
        content = b"".join([chunk async for chunk in response.body_iterator])
        parsed = json.loads(content)
        assert parsed["submission_id"] == str(sub.id)
        assert "data" in parsed
        assert parsed["export_version"] == "1.0"


# ══════════════════════════════════════════════════════════════
#  Router registration
# ══════════════════════════════════════════════════════════════

class TestSubmissionRouterRegistration:
    """Both form_builder routers merged at /api/v1/form-builder."""

    def test_submission_router_routes_in_app(self):
        from main import app
        routes = [r.path for r in app.routes]
        assert any("/form-builder/submissions" in p for p in routes), (
            "/form-builder/submissions routes not found"
        )

    def test_associations_route_in_app(self):
        from main import app
        routes = [r.path for r in app.routes]
        assert any("/form-builder/associations" in p for p in routes), (
            "/form-builder/associations routes not found"
        )

    def test_context_lookup_route_in_app(self):
        from main import app
        routes = [r.path for r in app.routes]
        assert any("context" in p and "form-builder" in p for p in routes), (
            "/form-builder/context/... route not found"
        )

    def test_validate_route_in_app(self):
        from main import app
        routes = [r.path for r in app.routes]
        assert any("submissions/validate" in p for p in routes), (
            "/form-builder/submissions/validate route not found"
        )

    def test_submission_router_registered_before_tasks(self):
        from main import app
        route_paths = [r.path for r in app.routes]
        sub_idx  = next((i for i, p in enumerate(route_paths) if "/form-builder/submissions" in p), None)
        task_idx = next((i for i, p in enumerate(route_paths) if "/tasks" in p), None)
        assert sub_idx is not None, "submission routes not found"
        assert task_idx is not None, "tasks routes not found"
        assert sub_idx < task_idx
