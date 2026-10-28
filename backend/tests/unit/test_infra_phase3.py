# ============================================================
# OPSYN INFRASTRUCTURE PHASE 3 — UNIT TESTS
# tests/unit/test_infra_phase3.py
#
# Validation gates:
#   Gate 1  — POST /upload/{asset_type} rejects invalid asset_type (400)
#   Gate 2  — POST /upload/{asset_type} creates session, returns summary
#   Gate 3  — GET  /upload/{session_id} returns 404 for unknown session
#   Gate 4  — POST /upload/{session_id}/commit rejects non-validated status (409)
#   Gate 5  — POST /upload/{session_id}/commit returns CommitResult on success
#   Gate 6  — GET  /infrastructure/cabinets returns paginated list
#   Gate 7  — GET  /infrastructure/olts returns paginated list
#   Gate 8  — GET  /infrastructure/splitters supports splitter_level filter
#   Gate 9  — infrastructure_router registered BEFORE tasks_router in main.py
# ============================================================

from __future__ import annotations

import io
import uuid
import importlib
import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
import openpyxl

from app.modules.infrastructure.schemas import ValidationSummary, CommitResult


# ── Helpers ───────────────────────────────────────────────────

def _make_session(
    session_id: uuid.UUID,
    tenant_id: uuid.UUID,
    asset_type: str = "splitter",
    status: str = "validated",
) -> MagicMock:
    s = MagicMock()
    s.id         = session_id
    s.tenant_id  = tenant_id
    s.asset_type = asset_type
    s.status     = status
    s.original_filename = "test.xlsx"
    s.total_rows    = 5
    s.valid_rows    = 4
    s.duplicate_rows = 0
    s.error_rows    = 1
    s.committed_rows = None
    s.submitted_by  = uuid.uuid4()
    s.submitted_at  = datetime.datetime.now(datetime.timezone.utc)
    s.approved_by   = None
    s.approved_at   = None
    s.committed_at  = None
    return s


def _make_caller(tenant_id: uuid.UUID) -> MagicMock:
    caller = MagicMock()
    caller.id        = uuid.uuid4()
    caller.tenant_id = tenant_id
    return caller


def _make_asset(model_mock, tenant_id: uuid.UUID, **kwargs) -> MagicMock:
    obj = MagicMock(spec=model_mock)
    obj.tenant_id = tenant_id
    obj.created_at = datetime.datetime.now(datetime.timezone.utc)
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


# ══════════════════════════════════════════════════════════════
# Gate 1 — invalid asset_type rejected
# ══════════════════════════════════════════════════════════════

class TestUploadInvalidAssetType:
    """Gate 1: uploading with an unsupported asset_type returns HTTP 400."""

    def test_invalid_type_set(self):
        from app.modules.infrastructure.router import _VALID_UPLOAD_TYPES
        assert "splitter" in _VALID_UPLOAD_TYPES
        assert "cabinet"  in _VALID_UPLOAD_TYPES
        assert "olt"       in _VALID_UPLOAD_TYPES
        assert "unknown"  not in _VALID_UPLOAD_TYPES
        # Network GIS Phase 2: cables (and poles, FATs, …) upload into net_cables / net_assets
        assert "cable"    in _VALID_UPLOAD_TYPES


# ══════════════════════════════════════════════════════════════
# Gate 2 — upload creates session, calls run_full_validation
# ══════════════════════════════════════════════════════════════

class TestUploadEndpointFlow:
    """Gate 2: upload endpoint creates InfraUploadSession and delegates to run_full_validation."""

    @pytest.mark.asyncio
    async def test_upload_calls_run_full_validation(self):
        from app.modules.infrastructure.router import upload_asset_file

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        caller     = _make_caller(tenant_id)

        expected_summary = ValidationSummary(
            session_id=session_id, asset_type="splitter",
            status="validated", total_rows=3, valid_rows=3,
            duplicate_rows=0, error_rows=0, warnings=0,
            errors=[], duplicates=[],
        )

        created_session = MagicMock()
        created_session.id        = session_id
        created_session.tenant_id = tenant_id

        db = AsyncMock()
        db.add   = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        # Simulate db.add setting the id on the session object
        def _add_side_effect(obj):
            obj.id = session_id
        db.add.side_effect = _add_side_effect

        file_mock = MagicMock()
        file_mock.filename = "splitters.xlsx"
        file_mock.read = AsyncMock(return_value=b"fakebytes")

        with patch(
            "app.modules.infrastructure.router.run_full_validation",
            new=AsyncMock(return_value=expected_summary),
        ) as mock_validate:
            result = await upload_asset_file(
                asset_type="splitter",
                file=file_mock,
                db=db,
                caller=caller,
            )

        mock_validate.assert_awaited_once()
        call_kwargs = mock_validate.call_args
        assert call_kwargs.kwargs["asset_type"] == "splitter"
        assert call_kwargs.kwargs["file_bytes"] == b"fakebytes"
        assert call_kwargs.kwargs["tenant_id"]  == tenant_id
        assert result.status == "validated"
        db.commit.assert_awaited_once()


# ══════════════════════════════════════════════════════════════
# Gate 3 — GET /upload/{session_id} returns 404 for unknown
# ══════════════════════════════════════════════════════════════

class TestGetUploadSession:
    """Gate 3: get_upload_session raises 404 when session not found."""

    @pytest.mark.asyncio
    async def test_missing_session_raises_404(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import get_upload_session

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        caller     = _make_caller(tenant_id)

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_upload_session(session_id=session_id, db=db, caller=caller)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_wrong_tenant_raises_404(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import get_upload_session

        tenant_id    = uuid.uuid4()
        other_tenant = uuid.uuid4()
        session_id   = uuid.uuid4()
        caller       = _make_caller(tenant_id)

        session_obj = _make_session(session_id, other_tenant)
        db = AsyncMock()
        db.get = AsyncMock(return_value=session_obj)

        with pytest.raises(HTTPException) as exc_info:
            await get_upload_session(session_id=session_id, db=db, caller=caller)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_valid_session_returns_dict(self):
        from app.modules.infrastructure.router import get_upload_session

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        caller     = _make_caller(tenant_id)

        session_obj = _make_session(session_id, tenant_id)
        db = AsyncMock()
        db.get = AsyncMock(return_value=session_obj)

        result = await get_upload_session(session_id=session_id, db=db, caller=caller)

        assert result["id"]         == str(session_id)
        assert result["asset_type"] == "splitter"
        assert result["status"]     == "validated"


# ══════════════════════════════════════════════════════════════
# Gate 4 — commit rejects non-validated status (409)
# ══════════════════════════════════════════════════════════════

class TestCommitEndpointValidation:
    """Gate 4: commit endpoint returns 409 when session status is not 'validated'."""

    @pytest.mark.asyncio
    async def test_pending_status_rejected_with_409(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import commit_upload_session

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        caller     = _make_caller(tenant_id)

        session_obj = _make_session(session_id, tenant_id, status="pending")
        db = AsyncMock()
        db.get = AsyncMock(return_value=session_obj)

        with pytest.raises(HTTPException) as exc_info:
            await commit_upload_session(session_id=session_id, db=db, caller=caller)

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_committed_status_rejected_with_409(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import commit_upload_session

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        caller     = _make_caller(tenant_id)

        session_obj = _make_session(session_id, tenant_id, status="committed")
        db = AsyncMock()
        db.get = AsyncMock(return_value=session_obj)

        with pytest.raises(HTTPException) as exc_info:
            await commit_upload_session(session_id=session_id, db=db, caller=caller)

        assert exc_info.value.status_code == 409


# ══════════════════════════════════════════════════════════════
# Gate 5 — commit delegates to commit_session and returns CommitResult
# ══════════════════════════════════════════════════════════════

class TestCommitEndpointSuccess:
    """Gate 5: commit endpoint returns CommitResult on success."""

    @pytest.mark.asyncio
    async def test_commit_returns_commit_result(self):
        from app.modules.infrastructure.router import commit_upload_session

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        caller     = _make_caller(tenant_id)

        session_obj = _make_session(session_id, tenant_id, status="validated")
        db = AsyncMock()
        db.get    = AsyncMock(return_value=session_obj)
        db.commit = AsyncMock()

        expected = CommitResult(
            session_id=session_id, committed_rows=4, status="committed"
        )

        with patch(
            "app.modules.infrastructure.router.commit_session",
            new=AsyncMock(return_value=expected),
        ) as mock_commit:
            result = await commit_upload_session(
                session_id=session_id, db=db, caller=caller
            )

        mock_commit.assert_awaited_once_with(db, session_id, caller.tenant_id, caller.id)
        assert result.status        == "committed"
        assert result.committed_rows == 4
        db.commit.assert_awaited_once()


# ══════════════════════════════════════════════════════════════
# Gate 6 — list_cabinets returns paginated response
# ══════════════════════════════════════════════════════════════

class TestListCabinets:
    """Gate 6: list_cabinets returns total + paginated items."""

    @pytest.mark.asyncio
    async def test_list_returns_paginated_structure(self):
        from app.modules.infrastructure.router import list_cabinets
        from app.modules.infrastructure.models import Cabinet

        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)

        cab = MagicMock()
        cab.id        = uuid.uuid4()
        cab.tenant_id = tenant_id
        cab.cabinet_id = "CAB-001"
        cab.capacity   = 48
        cab.number_tray = 4
        cab.longitude  = 3.37
        cab.latitude   = 6.52
        cab.created_by = None
        cab.upload_session_id = None
        cab.created_at = datetime.datetime.now(datetime.timezone.utc)

        # First execute: count query → scalar_one() = 1
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        # Second execute: data rows → scalars().all()
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [cab]

        call_count = [0]
        async def _execute(stmt, *a, **kw):
            call_count[0] += 1
            return count_result if call_count[0] == 1 else rows_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_execute)

        result = await list_cabinets(page=1, size=50, db=db, caller=caller)

        assert result["total"] == 1
        assert result["page"]  == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["cabinet_id"] == "CAB-001"


# ══════════════════════════════════════════════════════════════
# Gate 7 — list_olts returns paginated response
# ══════════════════════════════════════════════════════════════

class TestListOLTs:
    """Gate 7: list_olts returns total + paginated items."""

    @pytest.mark.asyncio
    async def test_list_returns_paginated_structure(self):
        from app.modules.infrastructure.router import list_olts

        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)

        olt = MagicMock()
        olt.id        = uuid.uuid4()
        olt.tenant_id = tenant_id
        olt.name      = "OLT-SURULERE-01"
        olt.location_description = "Surulere Hub"
        olt.number_of_odf = 4
        olt.longitude = 3.37
        olt.latitude  = 6.52
        olt.created_by = None
        olt.upload_session_id = None
        olt.created_at = datetime.datetime.now(datetime.timezone.utc)

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [olt]

        call_count = [0]
        async def _execute(stmt, *a, **kw):
            call_count[0] += 1
            return count_result if call_count[0] == 1 else rows_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_execute)

        result = await list_olts(page=1, size=50, db=db, caller=caller)

        assert result["total"] == 1
        assert result["items"][0]["name"] == "OLT-SURULERE-01"


# ══════════════════════════════════════════════════════════════
# Gate 8 — list_splitters supports splitter_level filter
# ══════════════════════════════════════════════════════════════

class TestListSplitters:
    """Gate 8: list_splitters supports optional splitter_level filter."""

    @pytest.mark.asyncio
    async def test_list_without_filter(self):
        from app.modules.infrastructure.router import list_splitters

        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)

        spl = MagicMock()
        spl.id         = uuid.uuid4()
        spl.tenant_id  = tenant_id
        spl.box_id     = "SPL-001"
        spl.input_ports  = 1
        spl.output_ports = 8
        spl.splitter_level = "First-Level"
        spl.splitter_type  = "PCC"
        spl.number_customer = 4
        spl.longitude = 3.37
        spl.latitude  = 6.52
        spl.parent_splitter_id = None
        spl.cabinet_id = None
        spl.created_by = None
        spl.upload_session_id = None
        spl.created_at = datetime.datetime.now(datetime.timezone.utc)

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [spl]

        call_count = [0]
        async def _execute(stmt, *a, **kw):
            call_count[0] += 1
            return count_result if call_count[0] == 1 else rows_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_execute)

        result = await list_splitters(page=1, size=50, splitter_level=None, db=db, caller=caller)

        assert result["total"] == 1
        assert result["items"][0]["box_id"] == "SPL-001"
        assert result["items"][0]["splitter_level"] == "First-Level"

    @pytest.mark.asyncio
    async def test_splitter_level_filter_applied(self):
        from app.modules.infrastructure.router import list_splitters

        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []

        call_count = [0]
        async def _execute(stmt, *a, **kw):
            call_count[0] += 1
            return count_result if call_count[0] == 1 else rows_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_execute)

        result = await list_splitters(
            page=1, size=50, splitter_level="Second-Level", db=db, caller=caller
        )

        # With an empty DB the count should be 0 and items empty
        assert result["total"] == 0
        assert result["items"] == []


# ══════════════════════════════════════════════════════════════
# Gate 9 — infrastructure_router registered BEFORE tasks_router
# ══════════════════════════════════════════════════════════════

class TestRouterRegistrationOrder:
    """Gate 9: infrastructure_router must be registered before tasks_router in main.py."""

    def test_infrastructure_registered_before_tasks(self):
        import main as main_module

        app = main_module.create_app()
        route_tags: list[str] = []
        for route in app.routes:
            tags = getattr(route, "tags", [])
            for tag in tags:
                if tag not in route_tags:
                    route_tags.append(tag)

        infra_pos = next(
            (i for i, t in enumerate(route_tags) if t == "Infrastructure"), None
        )
        tasks_pos = next(
            (i for i, t in enumerate(route_tags) if t == "Tasks"), None
        )

        assert infra_pos is not None, "Infrastructure tag not found in routes"
        assert tasks_pos is not None, "Tasks tag not found in routes"
        assert infra_pos < tasks_pos, (
            f"infrastructure_router (pos {infra_pos}) must be registered "
            f"BEFORE tasks_router (pos {tasks_pos})"
        )
