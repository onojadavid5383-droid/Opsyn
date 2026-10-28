# ============================================================
# OPSYN INFRASTRUCTURE AUDIT SERVICE
# app/modules/infrastructure/audit_service.py
#
# Single entry point for writing audit log entries on all
# FTTH asset actions (upload, delete, soft_delete, restore).
#
# Actor label uses the three-level fallback pattern established
# in the development log:
#   user.staff_profile.full_name → user.username → 'System'
# ============================================================

from __future__ import annotations

import uuid
import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.infrastructure.models import InfraAuditLog


async def write_audit_entry(
    db: AsyncSession,
    *,
    asset_type: str,
    asset_id: uuid.UUID | None,
    asset_key: str | None,
    action: str,
    session_id: uuid.UUID | None = None,
    actor_user: Any | None,            # User ORM instance, pre-loaded with staff_profile
    old_data: dict[str, Any] | None = None,
    new_data: dict[str, Any] | None = None,
    tenant_id: uuid.UUID,
) -> InfraAuditLog:
    """Write one entry to infrastructure_audit_log.

    actor_user must be fetched with selectinload(User.staff_profile) by the caller
    so that staff_profile is available without triggering a lazy load.
    """
    actor_id: uuid.UUID | None = None
    actor_label: str = "System"

    if actor_user is not None:
        actor_id = actor_user.id
        sp = getattr(actor_user, "staff_profile", None)
        full_name = getattr(sp, "full_name", None) if sp else None
        actor_label = full_name or getattr(actor_user, "username", None) or "System"

    entry = InfraAuditLog(
        tenant_id=tenant_id,
        asset_type=asset_type,
        asset_id=asset_id,
        asset_key=asset_key,
        action=action,
        session_id=session_id,
        actor_id=actor_id,
        actor_label=actor_label,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        old_data=old_data,
        new_data=new_data,
    )
    db.add(entry)
    await db.flush()
    return entry
