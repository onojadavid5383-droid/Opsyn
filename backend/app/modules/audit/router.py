# ============================================================
# OPSYN AUDIT MODULE — service.py + router.py
# Immutable append-only audit log — no UPDATE, no DELETE
# ============================================================

import uuid
import datetime
import csv
import io
from typing import Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.database import Base, get_db
from app.dependencies.permissions import check_permission
from app.modules.staff.models import User


# ── ORM Model ─────────────────────────────────────────────────
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id:           Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:    Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"), nullable=True)
    actor_id:     Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action:       Mapped[str]              = mapped_column(String(100), nullable=False)
    target_type:  Mapped[str | None]       = mapped_column(String(80))
    target_id:    Mapped[uuid.UUID | None]
    before_state: Mapped[dict | None]      = mapped_column(JSONB)
    after_state:  Mapped[dict | None]      = mapped_column(JSONB)
    ip_address:   Mapped[str | None]       = mapped_column(String(45))
    user_agent:   Mapped[str | None]       = mapped_column(Text)
    created_at:   Mapped[datetime.datetime] = mapped_column(
        default=datetime.datetime.utcnow, index=True
    )


# ── Service ───────────────────────────────────────────────────
class AuditService:
    """
    Append-only audit service.
    All writes use db.add() only — no updates, no deletes ever.
    password_hash is scrubbed before writing JSONB snapshots.
    """

    async def log(
        self,
        db:          AsyncSession,
        actor_id:    uuid.UUID,
        action:      str,
        target_type: str,
        target_id:   Optional[uuid.UUID] = None,
        before_state: Optional[dict[str, Any]] = None,
        after_state:  Optional[dict[str, Any]] = None,
        ip_address:   Optional[str] = None,
        user_agent:   Optional[str] = None,
        tenant_id:    Optional[uuid.UUID] = None,
    ) -> AuditLog:
        entry = AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before_state=self._scrub(before_state),
            after_state=self._scrub(after_state),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        # Use a savepoint so a failed flush doesn't poison the caller's session
        sp = await db.begin_nested()
        try:
            db.add(entry)
            await db.flush()
            await sp.commit()
        except Exception:
            await sp.rollback()
            raise
        return entry

    async def query(
        self,
        db:        AsyncSession,
        actor_id:  Optional[uuid.UUID] = None,
        action:    Optional[str] = None,
        from_dt:   Optional[datetime.datetime] = None,
        to_dt:     Optional[datetime.datetime] = None,
        page:      int = 1,
        size:      int = 50,
    ) -> dict:
        q = select(AuditLog).order_by(AuditLog.created_at.desc())
        if actor_id: q = q.where(AuditLog.actor_id == actor_id)
        if action:   q = q.where(AuditLog.action == action)
        if from_dt:  q = q.where(AuditLog.created_at >= from_dt)
        if to_dt:    q = q.where(AuditLog.created_at <= to_dt)
        total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        items = (await db.execute(q.offset((page - 1) * size).limit(size))).scalars().all()
        return {"items": items, "total": total, "page": page, "size": size,
                "total_pages": max(1, -(-total // size))}

    async def export_csv(self, db: AsyncSession, **filters) -> io.StringIO:
        result = await self.query(db, **filters, size=10000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["timestamp", "actor_id", "action", "target_type", "target_id", "ip_address"])
        for row in result["items"]:
            writer.writerow([
                row.created_at.isoformat(), str(row.actor_id or ""),
                row.action, row.target_type or "", str(row.target_id or ""),
                row.ip_address or "",
            ])
        output.seek(0)
        return output

    @staticmethod
    def _scrub(state: Optional[dict]) -> Optional[dict]:
        """Remove password_hash before writing to JSONB."""
        if not state:
            return state
        clean = dict(state)
        for key in ("password_hash", "password", "token", "secret"):
            if key in clean:
                clean[key] = "***"
        return clean


    async def log_event(
        self,
        actor_id:    uuid.UUID,
        action:      str,
        target_type: str,
        target_id:   Optional[str] = None,
        before_state: Optional[dict[str, Any]] = None,
        after_state:  Optional[dict[str, Any]] = None,
        ip_address:   Optional[str] = None,
        tenant_id:    Optional[uuid.UUID] = None,
    ) -> None:
        """Fire-and-forget audit log that opens its own DB session.
        Used by pipeline_service and other callers without a shared session."""
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            try:
                await self.log(
                    db=db,
                    actor_id=actor_id,
                    action=action,
                    target_type=target_type,
                    target_id=uuid.UUID(target_id) if target_id else None,
                    before_state=before_state,
                    after_state=after_state,
                    ip_address=ip_address,
                    tenant_id=tenant_id,
                )
                await db.commit()
            except Exception:
                await db.rollback()


audit_service = AuditService()


# ── Router ────────────────────────────────────────────────────
router = APIRouter()


@router.get("")
async def list_audit_logs(
    actor_id: Optional[uuid.UUID] = None,
    action:   Optional[str] = None,
    from_dt:  Optional[datetime.datetime] = None,
    to_dt:    Optional[datetime.datetime] = None,
    page:     int = Query(1, ge=1),
    size:     int = Query(50, ge=1, le=200),
    db:       AsyncSession = Depends(get_db),
    _:        User = Depends(check_permission("settings.admin")),
):
    result = await audit_service.query(db, actor_id, action, from_dt, to_dt, page, size)
    return {"success": True, "data": result}


@router.get("/export")
async def export_audit_csv(
    actor_id: Optional[uuid.UUID] = None,
    action:   Optional[str] = None,
    db:       AsyncSession = Depends(get_db),
    _:        User = Depends(check_permission("settings.admin")),
):
    buf = await audit_service.export_csv(db, actor_id=actor_id, action=action)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=opsyn-audit-{datetime.date.today()}.csv"}
    )
