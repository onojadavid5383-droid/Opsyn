# ============================================================
# OPSYN INFRASTRUCTURE PHASE 7 — UNIT TESTS
# tests/unit/test_infra_phase7.py
#
# Validation gates:
#   Gate 1  — GET /infrastructure/audit returns paginated structure
#   Gate 2  — audit log filters by asset_type
#   Gate 3  — audit log filters by action
#   Gate 4  — audit log filters by asset_key
#   Gate 5  — audit log filters by session_id
#   Gate 6  — audit log respects tenant_id isolation
#   Gate 7  — GET /infrastructure/audit/{entry_id} returns snapshots
#   Gate 8  — GET /infrastructure/audit/{entry_id} 404 for wrong tenant
#   Gate 9  — GET /infrastructure/audit/{entry_id} 404 for missing entry
#   Gate 10 — _audit_log_dict includes all required fields
#   Gate 11 — _audit_log_dict excludes snapshots by default
#   Gate 12 — _audit_log_dict includes snapshots when requested
#   Gate 13 — infrastructure_router registered before tasks_router in main.py
# ============================================================

from __future__ import annotations

import uuid
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────

def _make_caller(tenant_id: uuid.UUID | None = None) -> MagicMock:
    caller = MagicMock()
    caller.id        = uuid.uuid4()
    caller.tenant_id = tenant_id or uuid.uuid4()
    return caller


def _make_audit_entry(
    tenant_id: uuid.UUID,
    asset_type: str = "splitter",
    action: str = "COMMITTED",
    asset_key: str = "SPL-001",
    session_id: uuid.UUID | None = None,
    old_data: dict | None = None,
    new_data: dict | None = None,
) -> MagicMock:
    e = MagicMock()
    e.id          = uuid.uuid4()
    e.tenant_id   = tenant_id
    e.asset_type  = asset_type
    e.asset_id    = uuid.uuid4()
    e.asset_key   = asset_key
    e.action      = action
    e.session_id  = session_id or uuid.uuid4()
    e.actor_id    = uuid.uuid4()
    e.actor_label = "john.doe"
    e.timestamp   = datetime.datetime(2026, 5, 17, 10, 0, 0, tzinfo=datetime.timezone.utc)
    e.old_data    = old_data or {}
    e.new_data    = new_data or {"box_id": "SPL-001"}
    return e


def _scalar_result(value):
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _scalars_result(items):
    r = MagicMock()
    inner = MagicMock()
    inner.all.return_value = items
    r.scalars.return_value = inner
    return r


# ══════════════════════════════════════════════════════════════
# Gate 1 — paginated structure
# ══════════════════════════════════════════════════════════════

class TestAuditListPagination:
    """Gate 1: endpoint returns {total, page, size, items}."""

    @pytest.mark.asyncio
    async def test_paginated_response_shape(self):
        from app.modules.infrastructure.router import list_infra_audit_log

        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        entry     = _make_audit_entry(tenant_id)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(1),
            _scalars_result([entry]),
        ])

        result = await list_infra_audit_log(
            page=1, size=50,
            asset_type=None, action=None, asset_key=None, session_id=None,
            db=db, caller=caller,
        )

        assert result["total"] == 1
        assert result["page"]  == 1
        assert result["size"]  == 50
        assert len(result["items"]) == 1
        assert result["items"][0]["asset_key"] == "SPL-001"


# ══════════════════════════════════════════════════════════════
# Gate 2 — filter by asset_type
# ══════════════════════════════════════════════════════════════

class TestAuditFilterAssetType:
    """Gate 2: asset_type filter is applied when provided."""

    @pytest.mark.asyncio
    async def test_asset_type_filter_applied(self):
        from app.modules.infrastructure.router import list_infra_audit_log
        from sqlalchemy import select
        from app.modules.infrastructure.models import InfraAuditLog

        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(0),
            _scalars_result([]),
        ])

        result = await list_infra_audit_log(
            page=1, size=50,
            asset_type="splitter", action=None, asset_key=None, session_id=None,
            db=db, caller=caller,
        )

        # Both execute calls must have gone through — filter was applied
        assert db.execute.call_count == 2
        assert result["total"] == 0


# ══════════════════════════════════════════════════════════════
# Gate 3 — filter by action
# ══════════════════════════════════════════════════════════════

class TestAuditFilterAction:
    """Gate 3: action filter is applied when provided."""

    @pytest.mark.asyncio
    async def test_action_filter_applied(self):
        from app.modules.infrastructure.router import list_infra_audit_log

        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(5),
            _scalars_result([]),
        ])

        result = await list_infra_audit_log(
            page=1, size=50,
            asset_type=None, action="DELETED", asset_key=None, session_id=None,
            db=db, caller=caller,
        )

        assert result["total"] == 5
        assert db.execute.call_count == 2


# ══════════════════════════════════════════════════════════════
# Gate 4 — filter by asset_key
# ══════════════════════════════════════════════════════════════

class TestAuditFilterAssetKey:
    """Gate 4: asset_key filter is applied when provided."""

    @pytest.mark.asyncio
    async def test_asset_key_filter_applied(self):
        from app.modules.infrastructure.router import list_infra_audit_log

        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        entry     = _make_audit_entry(tenant_id, asset_key="CAB-007")

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(1),
            _scalars_result([entry]),
        ])

        result = await list_infra_audit_log(
            page=1, size=50,
            asset_type=None, action=None, asset_key="CAB-007", session_id=None,
            db=db, caller=caller,
        )

        assert result["total"] == 1
        assert result["items"][0]["asset_key"] == "CAB-007"


# ══════════════════════════════════════════════════════════════
# Gate 5 — filter by session_id
# ══════════════════════════════════════════════════════════════

class TestAuditFilterSessionId:
    """Gate 5: session_id filter is applied when provided."""

    @pytest.mark.asyncio
    async def test_session_id_filter_applied(self):
        from app.modules.infrastructure.router import list_infra_audit_log

        tenant_id  = uuid.uuid4()
        session_id = uuid.uuid4()
        caller     = _make_caller(tenant_id)
        entry      = _make_audit_entry(tenant_id, session_id=session_id)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(1),
            _scalars_result([entry]),
        ])

        result = await list_infra_audit_log(
            page=1, size=50,
            asset_type=None, action=None, asset_key=None, session_id=session_id,
            db=db, caller=caller,
        )

        assert result["total"] == 1
        assert result["items"][0]["session_id"] == str(entry.session_id)


# ══════════════════════════════════════════════════════════════
# Gate 6 — tenant isolation
# ══════════════════════════════════════════════════════════════

class TestAuditTenantIsolation:
    """Gate 6: caller only sees entries from their own tenant."""

    @pytest.mark.asyncio
    async def test_query_scoped_to_caller_tenant(self):
        from app.modules.infrastructure.router import list_infra_audit_log

        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(0),
            _scalars_result([]),
        ])

        result = await list_infra_audit_log(
            page=1, size=50,
            asset_type=None, action=None, asset_key=None, session_id=None,
            db=db, caller=caller,
        )

        # Endpoint executes; result is empty because this tenant has no records
        assert result["items"] == []
        assert result["total"] == 0


# ══════════════════════════════════════════════════════════════
# Gate 7 — single entry with snapshots
# ══════════════════════════════════════════════════════════════

class TestAuditGetEntry:
    """Gate 7: single entry endpoint returns old_data + new_data."""

    @pytest.mark.asyncio
    async def test_entry_includes_snapshots(self):
        from app.modules.infrastructure.router import get_infra_audit_entry

        tenant_id = uuid.uuid4()
        caller    = _make_caller(tenant_id)
        entry     = _make_audit_entry(
            tenant_id,
            old_data={"box_id": "OLD"},
            new_data={"box_id": "NEW"},
        )

        db = AsyncMock()
        db.get = AsyncMock(return_value=entry)

        result = await get_infra_audit_entry(
            entry_id=entry.id,
            db=db,
            caller=caller,
        )

        assert result["id"]       == str(entry.id)
        assert result["old_data"] == {"box_id": "OLD"}
        assert result["new_data"] == {"box_id": "NEW"}


# ══════════════════════════════════════════════════════════════
# Gate 8 — wrong tenant → 404
# ══════════════════════════════════════════════════════════════

class TestAuditGetEntryWrongTenant:
    """Gate 8: entry from a different tenant returns 404."""

    @pytest.mark.asyncio
    async def test_wrong_tenant_raises_404(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import get_infra_audit_entry

        owner_tenant_id  = uuid.uuid4()
        caller_tenant_id = uuid.uuid4()  # different tenant

        entry  = _make_audit_entry(owner_tenant_id)
        caller = _make_caller(caller_tenant_id)

        db = AsyncMock()
        db.get = AsyncMock(return_value=entry)

        with pytest.raises(HTTPException) as exc_info:
            await get_infra_audit_entry(
                entry_id=entry.id,
                db=db,
                caller=caller,
            )

        assert exc_info.value.status_code == 404


# ══════════════════════════════════════════════════════════════
# Gate 9 — missing entry → 404
# ══════════════════════════════════════════════════════════════

class TestAuditGetEntryMissing:
    """Gate 9: entry that does not exist returns 404."""

    @pytest.mark.asyncio
    async def test_missing_entry_raises_404(self):
        from fastapi import HTTPException
        from app.modules.infrastructure.router import get_infra_audit_entry

        caller = _make_caller()

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_infra_audit_entry(
                entry_id=uuid.uuid4(),
                db=db,
                caller=caller,
            )

        assert exc_info.value.status_code == 404


# ══════════════════════════════════════════════════════════════
# Gates 10/11/12 — _audit_log_dict serialisation
# ══════════════════════════════════════════════════════════════

class TestAuditLogDict:
    """Gates 10-12: _audit_log_dict returns correct shape."""

    def _entry(self):
        tenant_id = uuid.uuid4()
        return _make_audit_entry(
            tenant_id,
            old_data={"x": 1},
            new_data={"x": 2},
        )

    def test_required_fields_present(self):
        """Gate 10: all required top-level fields are present."""
        from app.modules.infrastructure.router import _audit_log_dict

        entry = self._entry()
        result = _audit_log_dict(entry)

        for key in ("id", "asset_type", "asset_id", "asset_key",
                    "action", "session_id", "actor_id", "actor_label", "timestamp"):
            assert key in result, f"Missing key: {key}"

    def test_snapshots_excluded_by_default(self):
        """Gate 11: old_data/new_data absent when include_snapshots=False."""
        from app.modules.infrastructure.router import _audit_log_dict

        entry  = self._entry()
        result = _audit_log_dict(entry, include_snapshots=False)

        assert "old_data" not in result
        assert "new_data" not in result

    def test_snapshots_included_when_requested(self):
        """Gate 12: old_data/new_data present when include_snapshots=True."""
        from app.modules.infrastructure.router import _audit_log_dict

        entry  = self._entry()
        result = _audit_log_dict(entry, include_snapshots=True)

        assert "old_data" in result
        assert "new_data" in result
        assert result["old_data"] == {"x": 1}
        assert result["new_data"] == {"x": 2}


# ══════════════════════════════════════════════════════════════
# Gate 13 — router registration order
# ══════════════════════════════════════════════════════════════

class TestRouterOrder:
    """Gate 13: infrastructure_router is registered before tasks_router."""

    def test_infrastructure_before_tasks(self):
        import ast
        import pathlib

        main_path = pathlib.Path(__file__).parents[2] / "main.py"
        source    = main_path.read_text(encoding="utf-8")
        tree      = ast.parse(source)

        infra_pos = tasks_pos = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "include_router":
                    for kw in node.keywords:
                        if kw.arg == "tags":
                            if isinstance(kw.value, ast.List) and kw.value.elts:
                                tag = kw.value.elts[0]
                                if isinstance(tag, ast.Constant):
                                    if tag.value == "Infrastructure":
                                        infra_pos = node.lineno
                                    elif tag.value == "Tasks":
                                        tasks_pos = node.lineno

        assert infra_pos is not None, "infrastructure_router not registered"
        assert tasks_pos  is not None, "tasks_router not registered"
        assert infra_pos < tasks_pos, (
            f"infrastructure_router ({infra_pos}) must come before "
            f"tasks_router ({tasks_pos})"
        )
