# ============================================================
# OPSYN NETWORK CODES — app/modules/network/codes.py
#
# Generated asset codes: <PREFIX>-<NNNN>, e.g. FAT-0014, POLE-0342,
# FDR-0003. One sequence per (tenant, asset type) or (tenant, cable
# category); the prefixes live in asset_types.py.
#
# The next number is one past the highest number already used with that
# prefix by the tenant — counting soft-deleted and design rows too, and
# (from Phase 8) codes of hard-deleted rows kept in network_audit_log — so a
# retired code is never handed out again. A transaction-scoped advisory
# lock per (tenant, prefix) serialises concurrent generators (two uploads
# committing at once cannot mint the same code); it is released when the
# caller's transaction ends.
#
# Codes typed in by people or brought in by import are left as they are;
# only numeric suffixes in the <PREFIX>-<digits> shape advance the sequence.
# ============================================================

from __future__ import annotations

import re
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.network.asset_types import ASSET_TYPES, CABLE_CATEGORIES

PAD = 4


def prefix_for(kind: str, key: str) -> str:
    if kind == "asset":
        return ASSET_TYPES[key].code_prefix
    return CABLE_CATEGORIES[key].code_prefix


def format_code(prefix: str, n: int) -> str:
    return f"{prefix}-{n:0{PAD}d}"


def code_pattern(prefix: str) -> str:
    """POSIX regex matching generated codes for this prefix (used in SQL)."""
    return f"^{re.escape(prefix)}-([0-9]+)$"


async def next_codes(db: AsyncSession, tenant_id: uuid.UUID, kind: str, key: str, count: int = 1,
                     *, lock: bool = True) -> list[str]:
    """Reserve `count` consecutive codes for this tenant and type.

    With lock=False nothing is reserved — used for the preview endpoint,
    whose answer may be overtaken by another writer.
    """
    prefix = prefix_for(kind, key)
    table = "net_assets" if kind == "asset" else "net_cables"
    if lock:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"netcode:{tenant_id}:{table}:{prefix}"},
        )
    # Hard-deleted rows (design edits) are gone from the table but not from
    # the audit trail (0092): counting both keeps a retired code retired
    kind_name = "asset" if kind == "asset" else "cable"
    highest = (await db.execute(text(f"""
        SELECT coalesce(max(substring(code FROM :pat)::bigint), 0) FROM (
            SELECT asset_code AS code FROM {table} WHERE tenant_id = :tid AND asset_code ~ :pat
            UNION ALL
            SELECT entity_code FROM network_audit_log
            WHERE tenant_id = :tid AND entity_type = :kind AND entity_code ~ :pat
        ) used
    """), {"tid": tenant_id, "pat": code_pattern(prefix), "kind": kind_name})).scalar_one()
    start = int(highest) + 1
    return [format_code(prefix, n) for n in range(start, start + count)]
