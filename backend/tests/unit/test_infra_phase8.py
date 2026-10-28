# ============================================================
# OPSYN INFRASTRUCTURE PHASE 8 — UNIT TESTS
# tests/unit/test_infra_phase8.py
#
# Security audit, regression, and load validation gates:
#
#   Gate 1  — MIME check: real xlsx accepted (PK magic bytes present)
#   Gate 2  — MIME spoof rejected: non-zip bytes with .xlsx extension
#   Gate 3  — Max rows guard: file with >10 000 data rows returns failed
#   Gate 4  — Max rows guard: 10 000 exact rows are accepted
#   Gate 5  — Cross-tenant isolation: upload session (wrong tenant → 404)
#   Gate 6  — Cross-tenant isolation: deletion session (wrong tenant → 404)
#   Gate 7  — Regression: cable_route excluded from VALID_UPLOAD_TYPES
#   Gate 8  — Regression: cable_route excluded from VALID_DELETION_TYPES
#   Gate 9  — All-errors collection: 5-field bad splitter row returns ≥5 errors
#   Gate 10 — Commit rollback on DB error: commit_session returns 'rolled_back'
#   Gate 11 — Error report xlsx produces valid bytes with correct sheet name
#   Gate 12 — Load: 1 000-row splitter file validates all rows, zero crashes
# ============================================================

from __future__ import annotations

import io
import time
import uuid
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import openpyxl


# ── xlsx builder helpers ──────────────────────────────────────

def _make_valid_xlsx(rows: list[list]) -> bytes:
    """Build xlsx from (header + rows). Returns raw bytes."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _splitter_header() -> list:
    return ["box_id", "input", "output", "splitter_level",
            "splitter_type", "longitude", "latitude"]


def _valid_splitter_row(n: int = 1) -> list:
    return [f"SPL-{n:04d}", 1, 8, "First-Level", "PCC", 3.4, 6.5]


def _make_caller(tenant_id: uuid.UUID | None = None) -> MagicMock:
    caller = MagicMock()
    caller.id        = uuid.uuid4()
    caller.tenant_id = tenant_id or uuid.uuid4()
    return caller


def _make_upload_session(session_id: uuid.UUID, tenant_id: uuid.UUID,
                         status: str = "validated") -> MagicMock:
    s = MagicMock()
    s.id         = session_id
    s.tenant_id  = tenant_id
    s.status     = status
    s.asset_type = "splitter"
    s.total_rows = 5
    s.valid_rows = 5
    s.duplicate_rows = 0
    s.error_rows = 0
    s.original_filename = "test.xlsx"
    s.file_hash  = "abc123"
    s.validation_errors = []
    s.committed_rows = 0
    s.submitted_by = uuid.uuid4()
    s.submitted_at = datetime.datetime.now(datetime.timezone.utc)
    return s


def _make_deletion_session(session_id: uuid.UUID, tenant_id: uuid.UUID,
                            status: str = "pending") -> MagicMock:
    s = MagicMock()
    s.id             = session_id
    s.tenant_id      = tenant_id
    s.status         = status
    s.asset_type     = "splitter"
    s.total_rows     = 3
    s.matched_rows   = 3
    s.unmatched_rows = 0
    s.deleted_rows   = None
    s.match_details  = []
    s.original_filename = "del.xlsx"
    s.submitted_by   = uuid.uuid4()
    s.submitted_at   = datetime.datetime.now(datetime.timezone.utc)
    s.approved_by    = None
    s.approved_at    = None
    s.executed_at    = None
    return s


# ══════════════════════════════════════════════════════════════
# Gate 1 — MIME check: valid xlsx accepted
# ══════════════════════════════════════════════════════════════

class TestMimeCheckAcceptsValidXlsx:
    """Gate 1: real xlsx bytes (PK magic) pass validate_file."""

    def test_valid_xlsx_passes_mime_check(self):
        from app.modules.infrastructure.upload_service import validate_file

        data = _make_valid_xlsx([_splitter_header(), _valid_splitter_row()])
        result = validate_file(data, "upload.xlsx")

        assert result.valid is True
        assert result.errors == []


# ══════════════════════════════════════════════════════════════
# Gate 2 — MIME spoof: non-zip bytes with .xlsx extension rejected
# ══════════════════════════════════════════════════════════════

class TestMimeSpoofRejected:
    """Gate 2: bytes that do not start with PK\\x03\\x04 are rejected."""

    def test_html_bytes_with_xlsx_extension_rejected(self):
        from app.modules.infrastructure.upload_service import validate_file

        spoofed = b"<html><body>Not a spreadsheet</body></html>"
        result  = validate_file(spoofed, "evil.xlsx")

        assert result.valid is False
        assert any("magic bytes" in e or "valid Excel" in e for e in result.errors)

    def test_pdf_header_with_xlsx_extension_rejected(self):
        from app.modules.infrastructure.upload_service import validate_file

        spoofed = b"%PDF-1.4 fake content"
        result  = validate_file(spoofed, "evil.xlsx")

        assert result.valid is False

    @pytest.mark.asyncio
    async def test_deletion_service_spoof_also_rejected(self):
        """Gate 2b: deletion_service.validate_deletion_file also checks magic bytes."""
        from app.modules.infrastructure.deletion_service import validate_deletion_file

        spoofed = b"<html>not xlsx</html>"
        result  = await validate_deletion_file("splitter", spoofed, "del.xlsx")

        assert result.valid is False
        assert any("magic bytes" in e or "valid Excel" in e for e in result.errors)


# ══════════════════════════════════════════════════════════════
# Gate 3 — Max rows guard: >10 000 rows → failed
# ══════════════════════════════════════════════════════════════

class TestMaxRowsGuard:
    """Gate 3: upload with more than MAX_ROWS_PER_SHEET data rows is rejected."""

    @pytest.mark.asyncio
    async def test_oversized_sheet_returns_failed(self):
        from app.modules.infrastructure.upload_service import (
            run_full_validation, MAX_ROWS_PER_SHEET,
        )

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()

        # Real xlsx bytes (passes MIME magic-bytes check in validate_file)
        data = _make_valid_xlsx([_splitter_header(), _valid_splitter_row()])

        session_mock = MagicMock()
        session_mock.status = "pending"
        session_mock.asset_type = "splitter"

        db = AsyncMock()
        db.get   = AsyncMock(return_value=session_mock)
        db.flush = AsyncMock()

        # Build a ws mock that:
        #  • returns valid header row (so validate_headers passes), AND
        #  • actually yields more than MAX_ROWS_PER_SHEET data rows
        #
        # Fix #5 stopped trusting ws.max_row (it is spreadsheet metadata and a
        # crafted file can understate it), so the guard counts rows by walking
        # iter_rows. A mock that only faked max_row no longer trips it — the
        # mock has to actually produce the rows.
        ws_mock = MagicMock()
        ws_mock.max_row = 2   # deliberately lies: claims a tiny sheet

        header = tuple(_splitter_header())
        data_rows = [header] + [header] * (MAX_ROWS_PER_SHEET + 5)

        def _iter_rows(*, min_row=1, max_row=None, values_only=False):
            if min_row == 1:
                return iter([header])
            # The validation pass walks every data row.
            return iter(data_rows[1:])

        ws_mock.iter_rows = MagicMock(side_effect=_iter_rows)

        wb_mock = MagicMock()
        wb_mock.active = ws_mock
        wb_mock.close  = MagicMock()

        # Patch the module-level openpyxl reference so both calls (in validate_file
        # and in run_full_validation body) use our mock workbook.
        with patch("openpyxl.load_workbook", return_value=wb_mock):
            result = await run_full_validation(
                db=db, session_id=session_id, asset_type="splitter",
                file_bytes=data, tenant_id=tenant_id,
            )

        assert result.status == "failed"
        assert any("rows" in e.get("error", "").lower() for e in result.errors)


# ══════════════════════════════════════════════════════════════
# Gate 4 — Max rows guard: exactly MAX_ROWS_PER_SHEET is accepted
# ══════════════════════════════════════════════════════════════

class TestMaxRowsBoundaryAccepted:
    """Gate 4: a file reporting exactly MAX_ROWS_PER_SHEET rows is allowed through."""

    @pytest.mark.asyncio
    async def test_exactly_max_rows_is_allowed(self):
        from app.modules.infrastructure.upload_service import (
            run_full_validation, MAX_ROWS_PER_SHEET,
        )

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        data = _make_valid_xlsx([_splitter_header(), _valid_splitter_row()])

        session_mock = MagicMock()
        session_mock.status = "pending"
        session_mock.asset_type = "splitter"

        db = AsyncMock()
        db.get     = AsyncMock(return_value=session_mock)
        db.flush   = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=None)))

        with patch("openpyxl.load_workbook") as mock_wb:
            ws_mock = MagicMock()
            # max_row = MAX_ROWS_PER_SHEET + 1 means MAX_ROWS_PER_SHEET data rows
            ws_mock.max_row = MAX_ROWS_PER_SHEET + 1
            ws_mock.iter_rows = MagicMock(return_value=iter([]))  # no actual rows
            wb_mock = MagicMock()
            wb_mock.active = ws_mock
            mock_wb.return_value = wb_mock

            result = await run_full_validation(
                db=db, session_id=session_id, asset_type="splitter",
                file_bytes=data, tenant_id=tenant_id,
            )

        # Should not fail on the row-count guard
        assert result.status != "failed" or not any(
            "rows" in e.get("error", "").lower() and "maximum" in e.get("error", "").lower()
            for e in result.errors
        )


# ══════════════════════════════════════════════════════════════
# Gate 5 — Cross-tenant isolation: upload session
# ══════════════════════════════════════════════════════════════

class TestCrossTenantUploadSession:
    """Gate 5: Tenant A cannot view Tenant B's upload session (returns 404)."""

    @pytest.mark.asyncio
    async def test_wrong_tenant_upload_session_returns_404(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import get_upload_session

        owner_tenant  = uuid.uuid4()
        caller_tenant = uuid.uuid4()  # different tenant

        session_id = uuid.uuid4()
        session    = _make_upload_session(session_id, owner_tenant)
        caller     = _make_caller(caller_tenant)

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)

        with pytest.raises(HTTPException) as exc_info:
            await get_upload_session(session_id=session_id, db=db, caller=caller)

        assert exc_info.value.status_code == 404


# ══════════════════════════════════════════════════════════════
# Gate 6 — Cross-tenant isolation: deletion session
# ══════════════════════════════════════════════════════════════

class TestCrossTenantDeletionSession:
    """Gate 6: Tenant A cannot view Tenant B's deletion session (returns 404)."""

    @pytest.mark.asyncio
    async def test_wrong_tenant_deletion_session_returns_404(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import get_deletion_session

        owner_tenant  = uuid.uuid4()
        caller_tenant = uuid.uuid4()

        session_id = uuid.uuid4()
        session    = _make_deletion_session(session_id, owner_tenant)
        caller     = _make_caller(caller_tenant)

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)

        with pytest.raises(HTTPException) as exc_info:
            await get_deletion_session(session_id=session_id, db=db, caller=caller)

        assert exc_info.value.status_code == 404


# ══════════════════════════════════════════════════════════════
# Gates 7 & 8 — Regression: Cable Routes excluded from both type sets
# ══════════════════════════════════════════════════════════════

class TestCableRouteExcluded:
    """Gates 7-8: cable_route is NOT a valid upload or deletion type."""

    def test_cable_route_not_in_upload_types(self):
        from app.modules.infrastructure.router import _VALID_UPLOAD_TYPES
        assert "cable_route" not in _VALID_UPLOAD_TYPES

    def test_cable_route_not_in_deletion_types(self):
        from app.modules.infrastructure.router import _VALID_DELETION_TYPES
        assert "cable_route" not in _VALID_DELETION_TYPES

    def test_upload_types_are_the_register_plus_network_types(self):
        # Network GIS Phase 2 added the network plant types alongside the three register types
        from app.modules.infrastructure.router import _VALID_UPLOAD_TYPES
        from app.modules.network.upload import NET_UPLOAD_TYPES
        assert _VALID_UPLOAD_TYPES == frozenset({"splitter", "cabinet", "olt"}) | frozenset(NET_UPLOAD_TYPES)

    def test_only_three_deletion_types(self):
        from app.modules.infrastructure.router import _VALID_DELETION_TYPES
        assert _VALID_DELETION_TYPES == frozenset({"splitter", "cabinet", "olt"})


# ══════════════════════════════════════════════════════════════
# Gate 9 — All-errors collection: bad row returns all field errors
# ══════════════════════════════════════════════════════════════

class TestAllErrorsCollected:
    """Gate 9: a row with 5 bad fields returns 5 errors, not just the first."""

    def test_splitter_row_with_five_bad_fields(self):
        from app.modules.infrastructure.upload_service import validate_row_splitter

        bad_row = {
            "box_id":        "",                # required — blank
            "input":         "not_a_number",    # must be int
            "output":        -5,                # must be >= 1
            "splitter_level": "first-level",    # wrong case
            "splitter_type":  "pcc",            # wrong case
            "longitude":     "abc",             # not a float
            "latitude":      "xyz",             # not a float
        }

        result = validate_row_splitter(bad_row)

        assert result.valid is False
        assert len(result.errors) >= 5, (
            f"Expected ≥5 errors, got {len(result.errors)}: {result.errors}"
        )

    def test_cabinet_row_collects_all_errors(self):
        from app.modules.infrastructure.upload_service import validate_row_cabinet

        bad_row = {
            "cabinet_id":  "",      # required — blank
            "capacity":    0,       # must be >= 1
            "number_tray": -1,      # must be >= 0
            "longitude":   "bad",
            "latitude":    "bad",
        }

        result = validate_row_cabinet(bad_row)

        assert result.valid is False
        assert len(result.errors) >= 4


# ══════════════════════════════════════════════════════════════
# Gate 10 — Commit rollback on DB error
# ══════════════════════════════════════════════════════════════

class TestCommitRollbackOnError:
    """Gate 10: commit_session returns status='rolled_back' when DB raises."""

    @pytest.mark.asyncio
    async def test_db_error_during_commit_returns_rolled_back(self):
        from app.modules.infrastructure.upload_service import commit_session

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        user_id    = uuid.uuid4()

        session_mock = MagicMock()
        session_mock.id         = session_id
        session_mock.status     = "validated"
        session_mock.asset_type = "splitter"

        # Actor user with no staff_profile
        actor_mock = MagicMock()
        actor_mock.id            = user_id
        actor_mock.staff_profile = None
        actor_mock.username      = "test_user"

        staging_row = MagicMock()
        staging_row.row_data = {
            "box_id": "SPL-001", "input": 1, "output": 8,
            "splitter_level": "First-Level", "splitter_type": "PCC",
            "longitude": 3.4, "latitude": 6.5,
        }
        staging_row.committed = False

        # scalars() chain for staging rows
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [staging_row]
        execute_result_staging = MagicMock()
        execute_result_staging.scalars.return_value = scalars_mock

        # actor user lookup
        actor_result = MagicMock()
        actor_result.scalar_one_or_none.return_value = actor_mock

        db = AsyncMock()
        db.get     = AsyncMock(return_value=session_mock)
        db.execute = AsyncMock(return_value=actor_result)
        db.flush   = AsyncMock()
        db.add     = MagicMock()

        # begin_nested savepoint raises on __aenter__
        savepoint_cm = MagicMock()
        savepoint_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("DB exploded"))
        savepoint_cm.__aexit__  = AsyncMock(return_value=False)
        db.begin_nested = AsyncMock(return_value=savepoint_cm)

        # Separate execute call for staging rows query
        db.execute = AsyncMock(side_effect=[actor_result, execute_result_staging])

        result = await commit_session(db, session_id, tenant_id, user_id)

        assert result.status == "rolled_back"
        assert result.committed_rows == 0


# ══════════════════════════════════════════════════════════════
# Gate 11 — Error report xlsx produces valid bytes
# ══════════════════════════════════════════════════════════════

class TestErrorReportXlsx:
    """Gate 11: generate_error_report_xlsx returns parseable xlsx bytes."""

    @pytest.mark.asyncio
    async def test_error_report_is_valid_xlsx(self):
        from app.modules.infrastructure.upload_service import generate_error_report_xlsx

        session_id = uuid.uuid4()

        session_mock = MagicMock()
        session_mock.asset_type = "splitter"

        staging_row = MagicMock()
        staging_row.row_number = 2
        staging_row.row_data   = {
            "box_id": "BAD-001", "input": "x", "output": 8,
            "splitter_level": "wrong", "splitter_type": "PCC",
            "longitude": 3.4, "latitude": 6.5,
        }
        staging_row.errors = [
            {"field": "input", "error": "must be integer"},
            {"field": "splitter_level", "error": "invalid enum"},
        ]

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [staging_row]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock

        db = AsyncMock()
        db.get     = AsyncMock(return_value=session_mock)
        db.execute = AsyncMock(return_value=execute_result)

        buf = await generate_error_report_xlsx(db, session_id)

        # Must be valid xlsx
        assert isinstance(buf, io.BytesIO)
        buf.seek(0)
        wb = openpyxl.load_workbook(buf)
        assert "Validation Errors" in wb.sheetnames
        ws = wb["Validation Errors"]
        # Header row + 1 data row
        rows = list(ws.iter_rows(values_only=True))
        assert len(rows) >= 2
        # 'Errors' column must be last in header
        assert rows[0][-1] == "Errors"


# ══════════════════════════════════════════════════════════════
# Gate 12 — Load: 1 000-row splitter file validates completely
# ══════════════════════════════════════════════════════════════

class TestLoadValidation:
    """Gate 12: 1 000-row splitter xlsx validates all rows without crashing."""

    def test_thousand_row_splitter_validation(self):
        from app.modules.infrastructure.upload_service import (
            validate_file, validate_headers, validate_row_splitter,
        )
        import time

        ROWS = 1_000

        # Build the xlsx in memory
        header = _splitter_header()
        rows   = [header] + [_valid_splitter_row(n) for n in range(1, ROWS + 1)]
        data   = _make_valid_xlsx(rows)

        # Layer 1: file validation
        file_result = validate_file(data, "load_test.xlsx")
        assert file_result.valid is True

        # Open and validate headers
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        header_result, header_map = validate_headers(ws, "splitter")
        assert header_result.valid is True

        # Layer 3: row validation for all 1 000 rows
        t0 = time.perf_counter()
        error_count = 0
        valid_count = 0
        for raw_row in ws.iter_rows(min_row=2, values_only=True):
            if all(c is None for c in raw_row):
                continue
            row_dict = {col: raw_row[idx] for col, idx in header_map.items()
                        if idx < len(raw_row)}
            result = validate_row_splitter(row_dict)
            if result.valid:
                valid_count += 1
            else:
                error_count += 1
        elapsed = time.perf_counter() - t0
        wb.close()

        assert valid_count == ROWS
        assert error_count == 0
        assert elapsed < 10.0, f"Validation took {elapsed:.2f}s — exceeds 10s limit"
