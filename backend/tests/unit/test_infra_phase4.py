# ============================================================
# OPSYN INFRASTRUCTURE PHASE 4 — UNIT TESTS
# tests/unit/test_infra_phase4.py
#
# Validation gates:
#   Gate 1  — invalid asset_type → 400
#   Gate 2  — malformed file → 422 with errors list
#   Gate 3  — valid file: session created with matched/unmatched counts
#   Gate 4  — matched_rows > 0, unmatched_rows > 0 in preview
#   Gate 5  — GET /deletion/{session_id} returns 404 for unknown session
#   Gate 6  — GET /deletion/{session_id} returns 404 for wrong-tenant session
#   Gate 7  — POST /deletion/{session_id}/execute rejects non-pending status (409)
#   Gate 8  — POST /deletion/{session_id}/execute calls execute_deletion, commits
#   Gate 9  — _VALID_DELETION_TYPES contains splitter/cabinet/olt only
# ============================================================

from __future__ import annotations

import io
import uuid
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import openpyxl

from app.modules.infrastructure.schemas import DeletionResult


# ── Helpers ───────────────────────────────────────────────────

def _make_caller(tenant_id: uuid.UUID) -> MagicMock:
    caller = MagicMock()
    caller.id        = uuid.uuid4()
    caller.tenant_id = tenant_id
    return caller


def _make_deletion_session(
    session_id: uuid.UUID,
    tenant_id: uuid.UUID,
    asset_type: str = "splitter",
    sts: str = "pending",
) -> MagicMock:
    s = MagicMock()
    s.id             = session_id
    s.tenant_id      = tenant_id
    s.asset_type     = asset_type
    s.status         = sts
    s.original_filename = "deletion.xlsx"
    s.total_rows     = 3
    s.matched_rows   = 2
    s.unmatched_rows = 1
    s.deleted_rows   = None
    s.match_details  = []
    s.submitted_by   = uuid.uuid4()
    s.submitted_at   = datetime.datetime.now(datetime.timezone.utc)
    s.approved_by    = None
    s.approved_at    = None
    s.executed_at    = None
    return s


def _make_xlsx_deletion_file(asset_type: str = "splitter") -> bytes:
    """Build a minimal valid deletion xlsx for the given asset_type."""
    wb = openpyxl.Workbook()
    ws = wb.active
    if asset_type == "splitter":
        ws.append(["box_id", "splitter_level"])
        ws.append(["SPL-001", "First-Level"])
    elif asset_type == "cabinet":
        ws.append(["cabinet_id", "capacity"])
        ws.append(["CAB-001", 48])
    elif asset_type == "olt":
        ws.append(["name"])
        ws.append(["OLT-SURULERE-01"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════
# Gate 9 — _VALID_DELETION_TYPES guard
# ══════════════════════════════════════════════════════════════

class TestDeletionTypeGuard:
    """Gate 9: only splitter/cabinet/olt are valid deletion types."""

    def test_valid_types(self):
        from app.modules.infrastructure.router import _VALID_DELETION_TYPES
        assert "splitter" in _VALID_DELETION_TYPES
        assert "cabinet"  in _VALID_DELETION_TYPES
        assert "olt"       in _VALID_DELETION_TYPES
        assert "cable_route" not in _VALID_DELETION_TYPES
        assert "unknown"     not in _VALID_DELETION_TYPES


# ══════════════════════════════════════════════════════════════
# Gate 1 — invalid asset_type → 400
# ══════════════════════════════════════════════════════════════

class TestDeletionInvalidAssetType:
    """Gate 1: unknown asset_type raises HTTP 400."""

    @pytest.mark.asyncio
    async def test_unknown_type_raises_400(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import upload_deletion_file

        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)

        file_mock = MagicMock()
        file_mock.filename = "del.xlsx"
        file_mock.read = AsyncMock(return_value=b"bytes")

        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await upload_deletion_file(
                asset_type="rocket",
                file=file_mock,
                db=db,
                caller=caller,
            )

        assert exc_info.value.status_code == 400


# ══════════════════════════════════════════════════════════════
# Gate 2 — malformed file → 422
# ══════════════════════════════════════════════════════════════

class TestDeletionMalformedFile:
    """Gate 2: a non-xlsx or empty file raises HTTP 422."""

    @pytest.mark.asyncio
    async def test_non_xlsx_raises_422(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import upload_deletion_file

        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)

        file_mock = MagicMock()
        file_mock.filename = "del.csv"
        file_mock.read = AsyncMock(return_value=b"col1,col2\n1,2")

        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await upload_deletion_file(
                asset_type="splitter",
                file=file_mock,
                db=db,
                caller=caller,
            )

        assert exc_info.value.status_code == 422
        # detail should include errors key
        assert "errors" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_missing_required_columns_raises_422(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import upload_deletion_file

        # Build xlsx missing 'splitter_level' column
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["box_id"])        # missing splitter_level
        ws.append(["SPL-001"])
        buf = io.BytesIO()
        wb.save(buf)
        bad_bytes = buf.getvalue()

        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)

        file_mock = MagicMock()
        file_mock.filename = "del.xlsx"
        file_mock.read = AsyncMock(return_value=bad_bytes)

        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await upload_deletion_file(
                asset_type="splitter",
                file=file_mock,
                db=db,
                caller=caller,
            )

        assert exc_info.value.status_code == 422


# ══════════════════════════════════════════════════════════════
# Gates 3 & 4 — valid file creates session with correct counts
# ══════════════════════════════════════════════════════════════

class TestDeletionSessionCreation:
    """Gates 3 & 4: valid file creates InfraDeletionSession with match counts."""

    @pytest.mark.asyncio
    async def test_session_created_with_match_counts(self):
        import app.modules.infrastructure.router as infra_router
        from app.modules.infrastructure.router import upload_deletion_file
        from app.modules.infrastructure.schemas import MatchResult

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        caller     = _make_caller(tenant_id)

        file_bytes = _make_xlsx_deletion_file("splitter")
        file_mock  = MagicMock()
        file_mock.filename = "splitter_del.xlsx"
        file_mock.read = AsyncMock(return_value=file_bytes)

        mock_match_results = [
            MatchResult(
                key={"box_id": "SPL-001", "splitter_level": "First-Level"},
                status="matched",
                asset_id=uuid.uuid4(),
            )
        ]

        db = AsyncMock()
        db.add    = MagicMock()
        db.commit = AsyncMock()

        # The upload endpoint also walks the splitter hierarchy to build the
        # cascade preview, which is a second db.execute(). A bare AsyncMock
        # returns an AsyncMock from db.execute(), whose .scalars() is itself
        # async and blows up on .all(). Give it a Result-shaped chain; this
        # scenario has no dependants.
        _rows = MagicMock()
        _rows.scalars.return_value.all.return_value = []
        _rows.all.return_value = []
        _rows.first.return_value = None
        db.execute = AsyncMock(return_value=_rows)

        async def _refresh(obj):
            obj.id             = session_id
            obj.matched_rows   = 1
            obj.unmatched_rows = 0

        db.refresh = AsyncMock(side_effect=_refresh)

        mock_fn = AsyncMock(return_value=mock_match_results)
        with patch.dict(infra_router._MATCH_FUNCTIONS, {"splitter": mock_fn}):
            result = await upload_deletion_file(
                asset_type="splitter",
                file=file_mock,
                db=db,
                caller=caller,
            )

        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        assert result["asset_type"]    == "splitter"
        assert result["matched_rows"]  == 1
        assert result["unmatched_rows"] == 0

    @pytest.mark.asyncio
    async def test_unmatched_rows_in_preview(self):
        import app.modules.infrastructure.router as infra_router
        from app.modules.infrastructure.router import upload_deletion_file
        from app.modules.infrastructure.schemas import MatchResult

        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)

        file_bytes = _make_xlsx_deletion_file("cabinet")
        file_mock  = MagicMock()
        file_mock.filename = "cabinet_del.xlsx"
        file_mock.read = AsyncMock(return_value=file_bytes)

        mock_match_results = [
            MatchResult(
                key={"cabinet_id": "CAB-001", "capacity": 48},
                status="unmatched",
                reason="No active cabinet found",
            )
        ]

        db = AsyncMock()
        db.add    = MagicMock()
        db.commit = AsyncMock()

        async def _refresh(obj):
            obj.matched_rows   = 0
            obj.unmatched_rows = 1

        db.refresh = AsyncMock(side_effect=_refresh)

        mock_fn = AsyncMock(return_value=mock_match_results)
        with patch.dict(infra_router._MATCH_FUNCTIONS, {"cabinet": mock_fn}):
            result = await upload_deletion_file(
                asset_type="cabinet",
                file=file_mock,
                db=db,
                caller=caller,
            )

        assert result["matched_rows"]   == 0
        assert result["unmatched_rows"] == 1


# ══════════════════════════════════════════════════════════════
# Gates 5 & 6 — GET /deletion/{session_id} 404 handling
# ══════════════════════════════════════════════════════════════

class TestGetDeletionSession:
    """Gates 5 & 6: 404 for unknown or wrong-tenant session."""

    @pytest.mark.asyncio
    async def test_missing_session_raises_404(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import get_deletion_session

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        caller     = _make_caller(tenant_id)

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_deletion_session(session_id=session_id, db=db, caller=caller)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_wrong_tenant_raises_404(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import get_deletion_session

        tenant_id    = uuid.uuid4()
        other_tenant = uuid.uuid4()
        session_id   = uuid.uuid4()
        caller       = _make_caller(tenant_id)

        session_obj = _make_deletion_session(session_id, other_tenant)
        db = AsyncMock()
        db.get = AsyncMock(return_value=session_obj)

        with pytest.raises(HTTPException) as exc_info:
            await get_deletion_session(session_id=session_id, db=db, caller=caller)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_valid_session_returns_dict(self):
        from app.modules.infrastructure.router import get_deletion_session

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        caller     = _make_caller(tenant_id)

        session_obj = _make_deletion_session(session_id, tenant_id)
        db = AsyncMock()
        db.get = AsyncMock(return_value=session_obj)

        result = await get_deletion_session(session_id=session_id, db=db, caller=caller)

        assert result["id"]          == str(session_id)
        assert result["asset_type"]  == "splitter"
        assert result["status"]      == "pending"
        assert result["matched_rows"] == 2


# ══════════════════════════════════════════════════════════════
# Gate 7 — execute rejects non-pending status (409)
# ══════════════════════════════════════════════════════════════

class TestExecuteDeletionValidation:
    """Gate 7: execute endpoint returns 409 for non-pending sessions."""

    @pytest.mark.asyncio
    async def test_executed_status_rejected_with_409(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import execute_deletion_session

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        caller     = _make_caller(tenant_id)

        session_obj = _make_deletion_session(session_id, tenant_id, sts="executed")
        db = AsyncMock()
        db.get = AsyncMock(return_value=session_obj)

        with pytest.raises(HTTPException) as exc_info:
            await execute_deletion_session(session_id=session_id, db=db, caller=caller)

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_failed_status_rejected_with_409(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import execute_deletion_session

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        caller     = _make_caller(tenant_id)

        session_obj = _make_deletion_session(session_id, tenant_id, sts="failed")
        db = AsyncMock()
        db.get = AsyncMock(return_value=session_obj)

        with pytest.raises(HTTPException) as exc_info:
            await execute_deletion_session(session_id=session_id, db=db, caller=caller)

        assert exc_info.value.status_code == 409


# ══════════════════════════════════════════════════════════════
# Gate 8 — execute calls execute_deletion and commits
# ══════════════════════════════════════════════════════════════

class TestExecuteDeletionSuccess:
    """Gate 8: execute endpoint delegates to execute_deletion and returns DeletionResult."""

    @pytest.mark.asyncio
    async def test_execute_returns_deletion_result(self):
        from app.modules.infrastructure.router import execute_deletion_session

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        caller     = _make_caller(tenant_id)

        session_obj = _make_deletion_session(session_id, tenant_id, sts="pending")
        db = AsyncMock()
        db.get    = AsyncMock(return_value=session_obj)
        db.commit = AsyncMock()

        expected = DeletionResult(
            session_id=session_id, deleted_rows=2, status="executed"
        )

        with patch(
            "app.modules.infrastructure.router.execute_deletion",
            new=AsyncMock(return_value=expected),
        ) as mock_exec:
            result = await execute_deletion_session(
                session_id=session_id, db=db, caller=caller
            )

        mock_exec.assert_awaited_once_with(db, session_id, caller.tenant_id, caller.id)
        assert result.status       == "executed"
        assert result.deleted_rows == 2
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_missing_session_raises_404(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import execute_deletion_session

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        caller     = _make_caller(tenant_id)

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await execute_deletion_session(session_id=session_id, db=db, caller=caller)

        assert exc_info.value.status_code == 404
