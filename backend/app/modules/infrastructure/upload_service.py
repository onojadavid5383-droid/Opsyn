# ============================================================
# OPSYN INFRASTRUCTURE UPLOAD SERVICE
# app/modules/infrastructure/upload_service.py
#
# Implements the four-layer validation engine:
#   1. File-level validation  (extension, size, parseable)
#   2. Header validation      (required columns, case-insensitive)
#   3. Row-level validation   (types, ranges, enum values)
#   4. Database validation    (duplicate detection per tenant)
#
# Also implements:
#   - Staging table write (run_full_validation)
#   - Atomic commit      (commit_session)
#   - Error report xlsx  (generate_error_report_xlsx)
# ============================================================

from __future__ import annotations

import hashlib
import io
import uuid
import datetime
from decimal import Decimal
from typing import Any

import openpyxl
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.infrastructure.models import (
    InfraUploadSession, InfraUploadStaging,
    SplitterBox, Cabinet, OLT,
)
from app.modules.staff.models import User
from app.modules.infrastructure.gis_utils import (
    validate_coordinates, make_point, normalize_coordinate,
)
from app.modules.infrastructure.schemas import (
    FileValidationResult, HeaderValidationResult,
    RowValidationResult, ValidationSummary, CommitResult,
)
from app.modules.infrastructure.audit_service import write_audit_entry

# ── Configuration ────────────────────────────────────────────
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024   # 10 MB
MAX_ROWS_PER_SHEET    = 10_000              # row limit per upload to prevent DoS

# xlsx is a ZIP container; its first 4 bytes are always PK\x03\x04
_XLSX_MAGIC = b'PK\x03\x04'

# Required Excel column names (case-insensitive) per asset type
REQUIRED_COLUMNS: dict[str, list[str]] = {
    "splitter":    ["box_id", "input", "output", "splitter_level",
                    "splitter_type", "longitude", "latitude"],
    "cabinet":     ["cabinet_id", "capacity", "number_tray",
                    "longitude", "latitude"],
    "olt":         ["name", "location", "longitude", "latitude"],
    "cable_route": [],
}

# All columns (display names) per asset type — used for error report header row
ASSET_COLUMNS_DISPLAY: dict[str, list[str]] = {
    "splitter":    ["box_id", "input", "output", "splitter_level",
                    "splitter_type", "number_customer", "longitude", "latitude"],
    "cabinet":     ["cabinet_id", "capacity", "number_tray",
                    "longitude", "latitude"],
    "olt":         ["name", "location", "number_of_ODF",
                    "longitude", "latitude"],
    "cable_route": [],
}

# Lowercase key versions (as stored in row_data JSONB)
ASSET_COLUMNS_KEYS: dict[str, list[str]] = {
    "splitter":    ["box_id", "input", "output", "splitter_level",
                    "splitter_type", "number_customer", "longitude", "latitude"],
    "cabinet":     ["cabinet_id", "capacity", "number_tray",
                    "longitude", "latitude"],
    "olt":         ["name", "location", "number_of_odf",
                    "longitude", "latitude"],
    "cable_route": [],
}


# ── Layer 1: File validation ─────────────────────────────────

def validate_file(file_bytes: bytes, filename: str) -> FileValidationResult:
    """Check extension, size, and parsability. Never raises."""
    errors: list[str] = []

    if not filename.lower().endswith(".xlsx"):
        errors.append(
            f"Invalid file type '{filename}' — only .xlsx files are accepted"
        )
        return FileValidationResult(valid=False, errors=errors)

    if len(file_bytes) == 0:
        errors.append("Uploaded file is empty")
        return FileValidationResult(valid=False, errors=errors)

    # MIME-type check: xlsx must have ZIP magic bytes PK\x03\x04
    if file_bytes[:4] != _XLSX_MAGIC:
        errors.append(
            "File content does not match .xlsx format — file must be a valid Excel workbook"
        )
        return FileValidationResult(valid=False, errors=errors)

    if len(file_bytes) > MAX_UPLOAD_SIZE_BYTES:
        mb = len(file_bytes) / (1024 * 1024)
        errors.append(
            f"File size {mb:.1f} MB exceeds the maximum of "
            f"{MAX_UPLOAD_SIZE_BYTES // (1024*1024)} MB"
        )
        return FileValidationResult(valid=False, errors=errors)

    try:
        openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception as exc:
        errors.append(
            f"File could not be parsed as a valid Excel file: {exc}"
        )
        return FileValidationResult(valid=False, errors=errors)

    return FileValidationResult(valid=True)


# ── Layer 2: Header validation ───────────────────────────────

def validate_headers(
    ws,
    asset_type: str,
    required_columns: list[str] | None = None,
) -> tuple[HeaderValidationResult, dict[str, int]]:
    """Check required columns (case-insensitive). Returns (result, header_map).

    header_map maps lowercase column name → 0-based column index.
    """
    required = required_columns if required_columns is not None else REQUIRED_COLUMNS.get(asset_type, [])
    header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)

    if header_row is None:
        return (
            HeaderValidationResult(valid=False, missing_columns=required),
            {},
        )

    # Build lowercase header → column index map
    header_map: dict[str, int] = {}
    for idx, cell in enumerate(header_row):
        if cell is not None:
            header_map[str(cell).strip().lower()] = idx

    missing = [col for col in required if col.lower() not in header_map]
    if missing:
        return (
            HeaderValidationResult(valid=False, missing_columns=missing),
            header_map,
        )

    return HeaderValidationResult(valid=True), header_map


async def get_upload_schema_snapshot(
    db: AsyncSession, asset_type: str, tenant_id: uuid.UUID,
) -> list[dict[str, Any]] | None:
    """Return the current published form snapshot for an infrastructure upload type."""
    from app.modules.form_builder.models import FormSchema, FormSchemaVersion
    machine_name = f"infra_{asset_type}_upload"
    result = await db.execute(
        select(FormSchemaVersion.field_snapshot)
        .join(FormSchema, FormSchema.id == FormSchemaVersion.schema_id)
        .where(
            FormSchema.tenant_id == tenant_id,
            FormSchema.machine_name == machine_name,
            FormSchema.status == "published",
            FormSchema.is_deleted == False,  # noqa: E712
            FormSchemaVersion.tenant_id == tenant_id,
            FormSchemaVersion.is_current == True,  # noqa: E712
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


# ── Layer 3: Row validation ───────────────────────────────────

def _get_str(row_dict: dict, key: str, max_len: int | None = None) -> tuple[str | None, str | None]:
    """Return (value, error) for a required string field."""
    val = row_dict.get(key)
    if val is None or str(val).strip() == "":
        return None, f"'{key}' is required and cannot be blank"
    s = str(val).strip()
    if max_len and len(s) > max_len:
        return None, f"'{key}' exceeds maximum length of {max_len} characters"
    return s, None


def _get_int(
    row_dict: dict, key: str, min_val: int | None = None, required: bool = True
) -> tuple[int | None, str | None]:
    """Return (value, error) for an integer field."""
    val = row_dict.get(key)
    if val is None or str(val).strip() == "":
        if required:
            return None, f"'{key}' is required and must be an integer"
        return None, None
    try:
        i = int(float(str(val).strip()))
    except (TypeError, ValueError):
        return None, f"'{key}' must be a valid integer (got '{val}')"
    if min_val is not None and i < min_val:
        return None, f"'{key}' must be >= {min_val} (got {i})"
    return i, None


def _get_decimal(
    row_dict: dict, key: str,
) -> tuple["Decimal | None", str | None, str | None]:
    """Return (value, error, warning) for a coordinate column.

    Parses to Decimal at the column's stored precision so the validated
    value is bit-for-bit what the database will hold.
    """
    return normalize_coordinate(row_dict.get(key), field=key)


def _validate_coordinates_row(
    row_dict: dict,
    errors: list[dict],
    warnings: list[str],
) -> None:
    """Shared longitude/latitude check for every asset row type.

    Writes the normalised Decimals back into row_dict so the commit step
    stores exactly the value that was validated — validating a rounded
    float and then storing an unrounded one is how the two drift apart.
    """
    lng, lng_err, lng_warn = _get_decimal(row_dict, "longitude")
    lat, lat_err, lat_warn = _get_decimal(row_dict, "latitude")

    if lng_err:
        errors.append({"field": "longitude", "value": row_dict.get("longitude"), "error": lng_err})
    if lat_err:
        errors.append({"field": "latitude", "value": row_dict.get("latitude"), "error": lat_err})
    if lng_warn:
        warnings.append(lng_warn)
    if lat_warn:
        warnings.append(lat_warn)

    if lng is not None and lat is not None:
        _, coord_errs = validate_coordinates(lng, lat)
        for ce in coord_errs:
            # validate_coordinates phrases messages in full ("Longitude
            # must be..."), so match case-insensitively — the previous
            # substring test only worked because the capital happened to
            # line up.
            field = "longitude" if "ongitude" in ce.lower() else "latitude"
            errors.append({"field": field, "value": None, "error": ce})

    if lng is not None and lat is None and not lng_err:
        errors.append({"field": "latitude", "value": row_dict.get("latitude"),
                       "error": "'latitude' is required"})
    if lat is not None and lng is None and not lng_err:
        errors.append({"field": "longitude", "value": row_dict.get("longitude"),
                       "error": "'longitude' is required"})

    if lng is not None:
        row_dict["longitude"] = str(lng)
    if lat is not None:
        row_dict["latitude"] = str(lat)


def validate_row_splitter(row_dict: dict) -> RowValidationResult:
    """Validate one splitter row. Collects ALL errors before returning."""
    errors: list[dict] = []
    warnings: list[str] = []

    # box_id
    box_id, err = _get_str(row_dict, "box_id", max_len=100)
    if err:
        errors.append({"field": "box_id", "value": row_dict.get("box_id"), "error": err})

    # input_ports
    _, err = _get_int(row_dict, "input", min_val=1)
    if err:
        errors.append({"field": "input", "value": row_dict.get("input"), "error": err})

    # output_ports
    _, err = _get_int(row_dict, "output", min_val=1)
    if err:
        errors.append({"field": "output", "value": row_dict.get("output"), "error": err})

    # splitter_level — normalize to canonical form (case-insensitive)
    level_raw = row_dict.get("splitter_level")
    if level_raw is None or str(level_raw).strip() == "":
        errors.append({
            "field": "splitter_level", "value": level_raw,
            "error": "splitter_level is required",
        })
        level = None
    else:
        level_normalized = str(level_raw).strip().lower()
        if level_normalized in ("first-level", "first level"):
            level = "First-Level"
        elif level_normalized in ("second-level", "second level"):
            level = "Second-Level"
        else:
            errors.append({
                "field": "splitter_level", "value": level_raw,
                "error": "splitter_level must be 'First-Level' or 'Second-Level' (case-insensitive)",
            })
            level = None

    # Update row_dict with normalized value
    if level:
        row_dict["splitter_level"] = level

    # splitter_type — normalize to canonical form (case-insensitive)
    stype_raw = row_dict.get("splitter_type")
    if stype_raw is None or str(stype_raw).strip() == "":
        errors.append({
            "field": "splitter_type", "value": stype_raw,
            "error": "splitter_type is required",
        })
        stype = None
    else:
        stype_normalized = str(stype_raw).strip().upper()
        if stype_normalized == "PCC":
            stype = "PCC"
        elif stype_normalized == "LEGACY":
            stype = "Legacy"
        else:
            errors.append({
                "field": "splitter_type", "value": stype_raw,
                "error": "splitter_type must be 'PCC' or 'Legacy' (case-insensitive)",
            })
            stype = None

    # Update row_dict with normalized value
    if stype:
        row_dict["splitter_type"] = stype

    # number_customer — optional, but must be int >= 0 if present
    nc_raw = row_dict.get("number_customer")
    if nc_raw is not None and str(nc_raw).strip() != "":
        _, err = _get_int(row_dict, "number_customer", min_val=0, required=False)
        if err:
            errors.append({"field": "number_customer", "value": nc_raw, "error": err})

    # coordinates
    _validate_coordinates_row(row_dict, errors, warnings)

    return RowValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def validate_row_cabinet(row_dict: dict) -> RowValidationResult:
    """Validate one cabinet row. Collects ALL errors before returning."""
    errors: list[dict] = []
    warnings: list[str] = []

    _, err = _get_str(row_dict, "cabinet_id", max_len=100)
    if err:
        errors.append({"field": "cabinet_id", "value": row_dict.get("cabinet_id"), "error": err})

    _, err = _get_int(row_dict, "capacity", min_val=1)
    if err:
        errors.append({"field": "capacity", "value": row_dict.get("capacity"), "error": err})

    _, err = _get_int(row_dict, "number_tray", min_val=0)
    if err:
        errors.append({"field": "number_tray", "value": row_dict.get("number_tray"), "error": err})

    _validate_coordinates_row(row_dict, errors, warnings)
    # (0, 0) is rejected by validate_coordinates — no separate warning

    return RowValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def validate_row_olt(row_dict: dict) -> RowValidationResult:
    """Validate one OLT row. Collects ALL errors before returning.

    Note: 'location' key in row_dict maps to location_description in ORM.
    After header lowercasing, 'number_of_ODF' becomes 'number_of_odf'.
    """
    errors: list[dict] = []
    warnings: list[str] = []

    _, err = _get_str(row_dict, "name", max_len=200)
    if err:
        errors.append({"field": "name", "value": row_dict.get("name"), "error": err})

    _, err = _get_str(row_dict, "location", max_len=500)
    if err:
        errors.append({"field": "location", "value": row_dict.get("location"), "error": err})

    # number_of_odf — optional integer >= 0
    odf_raw = row_dict.get("number_of_odf")
    if odf_raw is not None and str(odf_raw).strip() != "":
        _, err = _get_int(row_dict, "number_of_odf", min_val=0, required=False)
        if err:
            errors.append({"field": "number_of_odf", "value": odf_raw, "error": err})

    _validate_coordinates_row(row_dict, errors, warnings)
    # (0, 0) is rejected by validate_coordinates — no separate warning

    return RowValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


# ── Layer 4: Duplicate detection ─────────────────────────────

async def check_duplicate_splitter(
    db: AsyncSession, box_id: str, splitter_level: str, tenant_id: uuid.UUID
) -> bool:
    """Check for duplicate splitter using case-insensitive box_id comparison."""
    result = await db.execute(
        select(SplitterBox.id).where(
            func.lower(SplitterBox.box_id) == box_id.lower(),
            SplitterBox.splitter_level == splitter_level,
            SplitterBox.tenant_id == tenant_id,
            SplitterBox.is_deleted.is_(False),
        ).limit(1)
    )
    return result.scalar() is not None


async def check_duplicate_cabinet(
    db: AsyncSession, cabinet_id: str, tenant_id: uuid.UUID
) -> bool:
    """Check for duplicate cabinet using case-insensitive cabinet_id comparison."""
    result = await db.execute(
        select(Cabinet.id).where(
            func.lower(Cabinet.cabinet_id) == cabinet_id.lower(),
            Cabinet.tenant_id == tenant_id,
            Cabinet.is_deleted.is_(False),
        ).limit(1)
    )
    return result.scalar() is not None


async def check_duplicate_olt(
    db: AsyncSession, name: str, tenant_id: uuid.UUID
) -> bool:
    """Check for duplicate OLT using case-insensitive name comparison."""
    result = await db.execute(
        select(OLT.id).where(
            func.lower(OLT.name) == name.lower(),
            OLT.tenant_id == tenant_id,
            OLT.is_deleted.is_(False),
        ).limit(1)
    )
    return result.scalar() is not None


# ── Row validator dispatch ────────────────────────────────────

_ROW_VALIDATORS = {
    "splitter": validate_row_splitter,
    "cabinet":  validate_row_cabinet,
    "olt":      validate_row_olt,
}


def _get_duplicate_key(asset_type: str, row_dict: dict) -> dict | None:
    """Return the key dict used for duplicate checking, or None if row is invalid."""
    if asset_type == "splitter":
        box_id = row_dict.get("box_id")
        level  = row_dict.get("splitter_level")
        if box_id and level:
            return {"box_id": str(box_id), "splitter_level": str(level)}
    elif asset_type == "cabinet":
        cab_id = row_dict.get("cabinet_id")
        if cab_id:
            return {"cabinet_id": str(cab_id)}
    elif asset_type == "olt":
        name = row_dict.get("name")
        if name:
            return {"name": str(name)}
    return None


# ── Main orchestrator ─────────────────────────────────────────

async def run_full_validation(
    db: AsyncSession,
    session_id: uuid.UUID,
    asset_type: str,
    file_bytes: bytes,
    tenant_id: uuid.UUID,
    filename: str = "upload.xlsx",
) -> ValidationSummary:
    """Orchestrate all four validation layers. Write staging rows. Update session.

    Validation never stops early — all errors across all rows are collected.
    Returns ValidationSummary with status='validated' or 'failed'.
    """
    session_obj = await db.get(InfraUploadSession, session_id)
    if session_obj is None:
        raise ValueError(f"Upload session {session_id} not found")

    # Network plant types (poles, FATs, cables…) validate straight into
    # net_assets / net_cables shape — Network GIS Phase 2.
    from app.modules.network.upload import NET_UPLOAD_TYPES, validate_upload
    if asset_type in NET_UPLOAD_TYPES:
        return await validate_upload(db, session_obj, NET_UPLOAD_TYPES[asset_type],
                                     filename, file_bytes, tenant_id)

    upload_snapshot = await get_upload_schema_snapshot(db, asset_type, tenant_id)
    required_columns = None
    if upload_snapshot:
        required_columns = [
            str(field.get("field_key", "")).strip()
            for field in upload_snapshot
            if field.get("field_key") and (
                field.get("is_required") or (field.get("validation_rules") or {}).get("required")
            )
        ]
        # Coordinates and asset identity remain mandatory for the live asset tables.
        required_columns = list(dict.fromkeys([*(REQUIRED_COLUMNS.get(asset_type, [])), *required_columns]))

    # Mark as validating
    session_obj.status = "validating"
    await db.flush()

    all_errors: list[dict] = []
    all_duplicates: list[dict] = []
    staging_rows: list[InfraUploadStaging] = []

    # ── Layer 1: File validation ─────────────────────────────
    file_result = validate_file(file_bytes, filename)
    if not file_result.valid:
        session_obj.status = "failed"
        session_obj.validation_errors = [{"error": e} for e in file_result.errors]
        await db.flush()
        return ValidationSummary(
            session_id=session_id, asset_type=asset_type, status="failed",
            total_rows=0, valid_rows=0, duplicate_rows=0, error_rows=0,
            warnings=0, errors=[{"row": 0, "field": "file", "error": e} for e in file_result.errors],
            duplicates=[],
        )

    # Compute file hash and store
    session_obj.file_hash = hashlib.sha256(file_bytes).hexdigest()

    # ── Open workbook ────────────────────────────────────────
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active

    # ── Layer 2: Header validation ───────────────────────────
    header_result, header_map = validate_headers(ws, asset_type, required_columns)
    if not header_result.valid:
        session_obj.status = "failed"
        msg = f"Missing required columns: {', '.join(header_result.missing_columns)}"
        session_obj.validation_errors = [{"error": msg}]
        await db.flush()
        return ValidationSummary(
            session_id=session_id, asset_type=asset_type, status="failed",
            total_rows=0, valid_rows=0, duplicate_rows=0, error_rows=0,
            warnings=0, errors=[{"row": 0, "field": "header", "error": msg}],
            duplicates=[],
        )

    # ── Row count guard (DoS protection) ─────────────────────
    # Count actual data rows instead of trusting Excel metadata (ws.max_row can be spoofed)
    actual_row_count = 0
    for _ in ws.iter_rows(min_row=2, values_only=True):
        actual_row_count += 1
        if actual_row_count > MAX_ROWS_PER_SHEET:
            session_obj.status = "failed"
            msg = (
                f"File contains more than {MAX_ROWS_PER_SHEET} data rows; "
                f"maximum allowed is {MAX_ROWS_PER_SHEET}"
            )
            session_obj.validation_errors = [{"error": msg}]
            await db.flush()
            wb.close()
            return ValidationSummary(
                session_id=session_id, asset_type=asset_type, status="failed",
                total_rows=MAX_ROWS_PER_SHEET + 1, valid_rows=0, duplicate_rows=0, error_rows=0,
                warnings=0, errors=[{"row": 0, "field": "file", "error": msg}],
                duplicates=[],
            )

    # Reset iterator for validation pass
    wb.close()
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active

    # ── Layers 3 & 4: Row validation + duplicate check ───────
    row_validator = _ROW_VALIDATORS.get(asset_type)
    total_rows = 0
    valid_rows = 0
    duplicate_rows = 0
    error_rows = 0
    warning_count = 0

    for row_idx, raw_row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        # Skip entirely blank rows
        if all(cell is None for cell in raw_row):
            continue
        total_rows += 1

        # Build row dict using lowercase header map
        row_dict: dict[str, Any] = {}
        for col_name, col_idx in header_map.items():
            if col_idx < len(raw_row):
                row_dict[col_name] = raw_row[col_idx]

        # Row-level validation
        row_result = row_validator(row_dict) if row_validator else RowValidationResult(valid=True)
        if upload_snapshot:
            from app.modules.form_builder.validation_engine import ValidationContext, validate
            schema_fields = [{
                **field,
                # Uploads are validated independently of interactive user role and pipeline stage.
                "role_visibility": None, "role_editable": None,
                "stage_visible_from": None, "stage_required_at": None,
            } for field in upload_snapshot]
            schema_result = validate(
                schema_fields, row_dict,
                ValidationContext(tenant_id=str(tenant_id), submitting_user_role="", is_draft=False),
            )
            schema_errors = [
                {"field": error.field_key, "value": row_dict.get(error.field_key), "error": error.message}
                for error in schema_result.errors
            ]
            existing_errors = {(error.get("field"), error.get("error")) for error in row_result.errors}
            row_result.errors.extend(error for error in schema_errors if (error["field"], error["error"]) not in existing_errors)
            row_result.valid = not row_result.errors
            if row_result.valid:
                row_dict.update(schema_result.coerced_data)
        warning_count += len(row_result.warnings)

        is_duplicate = False
        if row_result.valid:
            # Duplicate check
            dup_key = _get_duplicate_key(asset_type, row_dict)
            if dup_key:
                if asset_type == "splitter":
                    is_duplicate = await check_duplicate_splitter(
                        db, dup_key["box_id"], dup_key["splitter_level"], tenant_id
                    )
                elif asset_type == "cabinet":
                    is_duplicate = await check_duplicate_cabinet(
                        db, dup_key["cabinet_id"], tenant_id
                    )
                elif asset_type == "olt":
                    is_duplicate = await check_duplicate_olt(
                        db, dup_key["name"], tenant_id
                    )

        if row_result.valid and is_duplicate:
            duplicate_rows += 1
            dup_key = _get_duplicate_key(asset_type, row_dict) or {}
            all_duplicates.append({"row": row_idx, **dup_key})
        elif not row_result.valid:
            error_rows += 1
            for err in row_result.errors:
                all_errors.append({"row": row_idx, **err})
        else:
            valid_rows += 1

        staging_rows.append(InfraUploadStaging(
            session_id=session_id,
            tenant_id=tenant_id,
            asset_type=asset_type,
            row_number=row_idx,
            row_data=row_dict,
            is_valid=row_result.valid,
            is_duplicate=is_duplicate,
            errors=row_result.errors if not row_result.valid else [],
            committed=False,
        ))

    wb.close()

    # Delete any pre-existing staging rows for this session (idempotent re-run)
    from sqlalchemy import delete as sa_delete
    await db.execute(
        sa_delete(InfraUploadStaging).where(
            InfraUploadStaging.session_id == session_id
        )
    )

    # Bulk-write staging rows
    db.add_all(staging_rows)

    # Update session record
    session_obj.status       = "validated"
    session_obj.total_rows   = total_rows
    session_obj.valid_rows   = valid_rows
    session_obj.duplicate_rows = duplicate_rows
    session_obj.error_rows   = error_rows
    session_obj.validation_errors = all_errors
    await db.flush()

    return ValidationSummary(
        session_id=session_id,
        asset_type=asset_type,
        status="validated",
        total_rows=total_rows,
        valid_rows=valid_rows,
        duplicate_rows=duplicate_rows,
        error_rows=error_rows,
        warnings=warning_count,
        errors=all_errors,
        duplicates=all_duplicates,
    )


# ── Commit logic ──────────────────────────────────────────────

def _build_orm_instance(asset_type: str, row_data: dict, tenant_id: uuid.UUID,
                        created_by: uuid.UUID, upload_session_id: uuid.UUID):
    """Build the live-table ORM model from a validated staging row."""
    # row_data holds the exact decimal text from the sheet. Keep it as a
    # Decimal for the WKT so the geometry column renders 6.524378 and not the
    # binary64 repr 6.524377999999, but hand the Double-backed longitude /
    # latitude columns a real float -- asyncpg rejects Decimal for a
    # FLOAT(53) bind parameter.
    lng_dec = Decimal(str(row_data["longitude"]))
    lat_dec = Decimal(str(row_data["latitude"]))
    lng = float(lng_dec)
    lat = float(lat_dec)
    pt  = make_point(lng_dec, lat_dec)
    custom_data = {
        key: value for key, value in row_data.items()
        if key not in ASSET_COLUMNS_KEYS.get(asset_type, [])
    }

    if asset_type == "splitter":
        nc = row_data.get("number_customer")
        return SplitterBox(
            tenant_id=tenant_id,
            box_id=str(row_data["box_id"]).strip(),
            input_ports=int(float(str(row_data["input"]))),
            output_ports=int(float(str(row_data["output"]))),
            splitter_level=str(row_data["splitter_level"]).strip(),
            splitter_type=str(row_data["splitter_type"]).strip(),
            number_customer=int(float(str(nc))) if nc is not None and str(nc).strip() != "" else None,
            longitude=lng, latitude=lat, location=pt,
            custom_data=custom_data,
            created_by=created_by,
            upload_session_id=upload_session_id,
        )

    if asset_type == "cabinet":
        return Cabinet(
            tenant_id=tenant_id,
            cabinet_id=str(row_data["cabinet_id"]).strip(),
            capacity=int(float(str(row_data["capacity"]))),
            number_tray=int(float(str(row_data["number_tray"]))),
            longitude=lng, latitude=lat, location=pt,
            custom_data=custom_data,
            created_by=created_by,
            upload_session_id=upload_session_id,
        )

    if asset_type == "olt":
        odf = row_data.get("number_of_odf")
        return OLT(
            tenant_id=tenant_id,
            name=str(row_data["name"]).strip(),
            location_description=str(row_data["location"]).strip(),
            number_of_odf=int(float(str(odf))) if odf is not None and str(odf).strip() != "" else None,
            longitude=lng, latitude=lat, location=pt,
            custom_data=custom_data,
            created_by=created_by,
            upload_session_id=upload_session_id,
        )

    raise ValueError(f"Unsupported asset_type: {asset_type}")


def _asset_key(asset_type: str, row_data: dict) -> str:
    if asset_type == "splitter":
        return str(row_data.get("box_id", ""))
    if asset_type == "cabinet":
        return str(row_data.get("cabinet_id", ""))
    if asset_type == "olt":
        return str(row_data.get("name", ""))
    return ""


async def commit_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    tenant_id: uuid.UUID,
    approved_by_user_id: uuid.UUID,
) -> CommitResult:
    """Atomically move valid staging rows to live tables.

    Uses a savepoint (begin_nested) so that a failure rolls back only the
    live-table inserts while the session status update still commits.
    All-or-nothing: zero rows committed on any exception.
    """
    session_obj = await db.get(InfraUploadSession, session_id)
    if session_obj is None:
        raise ValueError(f"Session {session_id} not found")

    # Fetch approver with staff_profile for actor_label resolution
    actor_user = (await db.execute(
        select(User)
        .where(User.id == approved_by_user_id)
        .options(selectinload(User.staff_profile))
    )).scalar_one_or_none()

    # Fetch valid, non-duplicate staging rows
    staging_result = await db.execute(
        select(InfraUploadStaging).where(
            InfraUploadStaging.session_id == session_id,
            InfraUploadStaging.is_valid.is_(True),
            InfraUploadStaging.is_duplicate.is_(False),
            InfraUploadStaging.committed.is_(False),
        ).order_by(InfraUploadStaging.row_number)
    )
    rows_to_commit = staging_result.scalars().all()

    committed_count = 0
    asset_type = session_obj.asset_type

    from app.modules.network.upload import NET_UPLOAD_TYPES, commit_rows
    net_type = NET_UPLOAD_TYPES.get(asset_type)

    try:
        async with await db.begin_nested():  # type: ignore[attr-defined]
            if net_type is not None:
                committed_count = await commit_rows(
                    db, net_type, list(rows_to_commit), tenant_id, actor_user, session_id,
                )
            for staging_row in (rows_to_commit if net_type is None else ()):
                orm_obj = _build_orm_instance(
                    asset_type, staging_row.row_data,
                    tenant_id, approved_by_user_id, session_id,
                )
                db.add(orm_obj)
                await db.flush()   # get the generated id

                # Write audit log entry
                await write_audit_entry(
                    db,
                    asset_type=asset_type,
                    asset_id=orm_obj.id,
                    asset_key=_asset_key(asset_type, staging_row.row_data),
                    action="upload",
                    session_id=session_id,
                    actor_user=actor_user,
                    old_data=None,
                    new_data=staging_row.row_data,
                    tenant_id=tenant_id,
                )

                committed_count += 1

            # Dual-write (Network GIS Phase 2): mirror the uploaded
            # OLTs / cabinets / splitters into net_assets in the same savepoint
            if net_type is None and committed_count:
                from app.modules.network.backfill import mirror_uploaded
                await mirror_uploaded(db, tenant_id)

            # Mark staging rows as committed AFTER all inserts succeed (inside savepoint)
            for staging_row in rows_to_commit:
                staging_row.committed = True

    except Exception as exc:
        # Savepoint rolled back all live-table inserts
        # Staging rows are NOT marked as committed, so retry is safe
        session_obj.status = "rolled_back"
        await db.flush()
        return CommitResult(
            session_id=session_id,
            committed_rows=0,
            status="rolled_back",
            error=str(exc),
        )

    # Success: update session
    session_obj.status         = "committed"
    session_obj.committed_rows = committed_count
    session_obj.approved_by    = approved_by_user_id
    session_obj.approved_at    = datetime.datetime.now(datetime.timezone.utc)
    session_obj.committed_at   = datetime.datetime.now(datetime.timezone.utc)
    await db.flush()

    return CommitResult(
        session_id=session_id,
        committed_rows=committed_count,
        status="committed",
    )


# ── Error report xlsx generation ─────────────────────────────

async def generate_error_report_xlsx(
    db: AsyncSession, session_id: uuid.UUID
) -> io.BytesIO:
    """Stream downloadable .xlsx error report for invalid staging rows.

    Columns: all original asset columns + 'Errors' column.
    """
    # Fetch session to get asset_type
    session_obj = await db.get(InfraUploadSession, session_id)
    asset_type = session_obj.asset_type if session_obj else "splitter"

    # Fetch invalid staging rows ordered by row_number
    result = await db.execute(
        select(InfraUploadStaging).where(
            InfraUploadStaging.session_id == session_id,
            InfraUploadStaging.is_valid.is_(False),
        ).order_by(InfraUploadStaging.row_number)
    )
    invalid_rows = result.scalars().all()

    display_cols = ASSET_COLUMNS_DISPLAY.get(asset_type, [])
    key_cols     = ASSET_COLUMNS_KEYS.get(asset_type, [])
    if session_obj:
        snapshot = await get_upload_schema_snapshot(db, asset_type, session_obj.tenant_id)
        configured_fields = [field for field in (snapshot or []) if field.get("field_key")]
        key_cols = list(dict.fromkeys([*key_cols, *(str(field["field_key"]) for field in configured_fields)]))
        labels = {str(field["field_key"]): str(field.get("label") or field["field_key"]) for field in configured_fields}
        display_cols = [labels.get(key, key) for key in key_cols]
    from app.modules.network.upload import NET_UPLOAD_TYPES
    if asset_type in NET_UPLOAD_TYPES:
        # Staged network rows are normalised: show the base fields as stored
        u = NET_UPLOAD_TYPES[asset_type]
        key_cols = ["asset_code", "name", "lifecycle_status"] + (
            ["capacity"] if u.kind == "asset" else ["cable_category", "fiber_count", "source_asset_code", "dest_asset_code"]
        )
        display_cols = key_cols

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Validation Errors"

    # Header row: original columns + Row# + Errors
    ws.append(["Row #"] + display_cols + ["Errors"])

    for staging_row in invalid_rows:
        rd = staging_row.row_data or {}
        # Build row values in original column order
        values = [rd.get(k, "") for k in key_cols]
        # Flatten errors to a readable string
        error_msgs = "; ".join(
            e.get("error", "") for e in (staging_row.errors or [])
        )
        ws.append([staging_row.row_number] + values + [error_msgs])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
