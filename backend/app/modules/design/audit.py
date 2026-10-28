# ============================================================
# OPSYN NETWORK AUDIT — app/modules/design/audit.py
# Network GIS Phase 8. Changes to net_assets / net_cables / net_connections
# are recorded by a database trigger (migration 0092) into
# network_audit_log; this module tells it who is acting, switches it to
# one-summary-row mode for bulk replacements, and reads the trail back
# (network_audit_trail = network_audit_log ∪ infrastructure_audit_log).
#
#   audited(feature)   a check_permission() that also stamps the caller on
#                      the request's transaction — used on the network and
#                      design write endpoints
#   set_actor()        the same, for code paths without the dependency
#   bulk()             the trigger stays quiet for this transaction; the
#                      caller writes one summary row (summary())
# ============================================================

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.permissions import check_permission


def actor_label(caller: Any) -> str:
    sp = getattr(caller, "staff_profile", None)
    return (getattr(sp, "full_name", None) if sp else None) or getattr(caller, "username", None) or "System"


async def set_actor(db: AsyncSession, caller: Any) -> None:
    """Who the audit trigger records for the rest of this transaction."""
    if caller is None:
        return
    await db.execute(text("SELECT set_config('app.user_id', :u, true), set_config('app.actor_label', :l, true)"),
                     {"u": str(caller.id), "l": actor_label(caller)[:200]})


def audited(feature_key: str):
    """check_permission(feature_key) that also stamps the caller for the audit trigger."""
    checker = check_permission(feature_key)

    async def _dep(db: AsyncSession = Depends(get_db), caller: Any = Depends(checker)) -> Any:
        await set_actor(db, caller)
        return caller
    return _dep


async def bulk(db: AsyncSession, on: bool = True) -> None:
    """Row-by-row audit off (on=True) or back on for this transaction."""
    await db.execute(text("SELECT set_config('app.audit_bulk', :v, true)"), {"v": "off" if on else ""})


async def summary(db: AsyncSession, tid: uuid.UUID, design_id: uuid.UUID, action: str, caller: Any,
                  old: dict[str, Any] | None, new: dict[str, Any] | None, code: str | None = None) -> None:
    """One row for a bulk change (a whole working set replaced)."""
    await db.execute(text("""
        INSERT INTO network_audit_log (tenant_id, entity_type, entity_id, entity_code, design_id, action,
                                       actor_id, actor_label, old_data, new_data)
        VALUES (:tid, 'design', :d, :code, :d, :action, :actor, :label, CAST(:old AS jsonb), CAST(:new AS jsonb))
    """), {"tid": tid, "d": design_id, "code": code, "action": action,
           "actor": getattr(caller, "id", None), "label": actor_label(caller) if caller else "System",
           "old": json.dumps(old, default=str) if old is not None else None,
           "new": json.dumps(new, default=str) if new is not None else None})


# The network service also writes its own infrastructure_audit_log entry for
# a live edit (whole records, from before 0092). Where the trigger recorded
# the same change (same entity and action within seconds), that entry is
# folded into the trigger's, which says exactly what changed.
_NOT_A_REPEAT = """
    AND NOT (t.source = 'infrastructure' AND EXISTS (
        SELECT 1 FROM network_audit_log n
        WHERE n.entity_id = t.entity_id AND n.action = t.action
          AND abs(extract(epoch FROM n.occurred_at - t.occurred_at)) < 5))
"""


def _row(r: Any) -> dict[str, Any]:
    return {"id": str(r.id), "entity_type": r.entity_type, "entity_id": str(r.entity_id) if r.entity_id else None,
            "entity_code": r.entity_code, "action": r.action, "actor": r.actor_label,
            "occurred_at": r.occurred_at.isoformat(), "changed_fields": r.changed_fields or [],
            "old": r.old_data, "new": r.new_data, "source": r.source}


async def entity_history(db: AsyncSession, tid: uuid.UUID, entity_id: uuid.UUID, limit: int = 100) -> list[dict[str, Any]]:
    rows = (await db.execute(text("""
        SELECT * FROM network_audit_trail t WHERE t.tenant_id = :tid AND t.entity_id = :id
    """ + _NOT_A_REPEAT + """
        ORDER BY t.occurred_at DESC LIMIT :n
    """), {"tid": tid, "id": entity_id, "n": limit})).all()
    return [_row(r) for r in rows]


async def design_history(db: AsyncSession, tid: uuid.UUID, design_id: uuid.UUID, limit: int = 200) -> list[dict[str, Any]]:
    rows = (await db.execute(text("""
        SELECT * FROM network_audit_trail t WHERE t.tenant_id = :tid AND t.design_id = :d
    """ + _NOT_A_REPEAT + """
        ORDER BY t.occurred_at DESC LIMIT :n
    """), {"tid": tid, "d": design_id, "n": limit})).all()
    return [_row(r) for r in rows]
