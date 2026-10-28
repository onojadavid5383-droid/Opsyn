# ============================================================
# OPSYN INFRASTRUCTURE SCHEMAS — app/modules/infrastructure/schemas.py
# Pydantic models for validation results, upload sessions,
# commit outcomes, and deletion workflow.
# ============================================================

from __future__ import annotations

import uuid
from typing import Any
from pydantic import BaseModel


# ── Row-level error (stored in JSONB) ────────────────────────

class RowError(BaseModel):
    row: int
    field: str
    value: Any = None
    error: str


# ── File and header validation ───────────────────────────────

class FileValidationResult(BaseModel):
    valid: bool
    errors: list[str] = []


class HeaderValidationResult(BaseModel):
    valid: bool
    missing_columns: list[str] = []


# ── Per-row validation result (internal, not persisted) ──────

class RowValidationResult(BaseModel):
    valid: bool
    errors: list[dict[str, Any]] = []   # {field, error, value}
    warnings: list[str] = []
    is_duplicate: bool = False


# ── Full validation summary — mirrors section 4.4 of the plan

class DuplicateRef(BaseModel):
    row: int
    key: dict[str, Any]


class ValidationSummary(BaseModel):
    session_id: uuid.UUID
    asset_type: str
    status: str                          # validated | failed
    total_rows: int
    valid_rows: int
    duplicate_rows: int
    error_rows: int
    warnings: int
    errors: list[dict[str, Any]]         # list of RowError dicts
    duplicates: list[dict[str, Any]]


# ── Commit result ────────────────────────────────────────────

class CommitResult(BaseModel):
    session_id: uuid.UUID
    committed_rows: int
    status: str                          # committed | rolled_back
    error: str | None = None


# ── Deletion workflow schemas ────────────────────────────────

class DeletionValidationResult(BaseModel):
    valid: bool
    asset_type: str
    total_rows: int
    errors: list[str] = []
    keys: list[dict[str, Any]] = []      # parsed deletion keys from file


class MatchResult(BaseModel):
    key: dict[str, Any]
    status: str                          # matched | unmatched
    asset_id: uuid.UUID | None = None
    reason: str | None = None


class DeletionResult(BaseModel):
    session_id: uuid.UUID
    deleted_rows: int
    """Rows the approver named in the deletion file and actually removed."""
    cascaded_rows: int = 0
    """Dependants removed with them: splitters under a deleted cabinet, or
    below a deleted First-Level splitter. These were never named in the file,
    so the UI must show them separately rather than folding them into
    deleted_rows -- otherwise the number no longer matches the spreadsheet."""
    status: str                          # executed | failed
    error: str | None = None
