# ============================================================
# OPSYN TIMELINE WRITER — app/modules/activity/service.py
#
# All writes to activity_timeline go through this service.
# INSERT-only: no UPDATE, no DELETE.
#
# entity_type: "task" | "project" | "onboarding" | "outage"
# event_type:  "comment" | "state_change" | "stage_event" | "system"
# ============================================================

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.core.context import tenant_id_ctx


class TimelineWriterService:

    # ── Public write helpers ─────────────────────────────────

    async def write_user_comment(
        self,
        db:          AsyncSession,
        entity_type: str,
        entity_id:   uuid.UUID,
        actor_id:    uuid.UUID,
        body:        str,
        meta:        Optional[dict[str, Any]] = None,
    ) -> uuid.UUID:
        """Record a user-authored comment on any entity."""
        return await self._insert(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type="comment",
            actor_id=actor_id,
            body=body,
            meta=meta or {},
        )

    async def write_system_event(
        self,
        db:          AsyncSession,
        entity_type: str,
        entity_id:   uuid.UUID,
        body:        str,
        meta:        Optional[dict[str, Any]] = None,
        actor_id:    Optional[uuid.UUID] = None,
    ) -> uuid.UUID:
        """Record an automated/system-generated event (no human actor required)."""
        return await self._insert(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type="system",
            actor_id=actor_id,
            body=body,
            meta=meta or {},
        )

    async def write_state_change(
        self,
        db:          AsyncSession,
        entity_type: str,
        entity_id:   uuid.UUID,
        actor_id:    uuid.UUID,
        from_state:  Optional[str],
        to_state:    str,
        meta:        Optional[dict[str, Any]] = None,
    ) -> uuid.UUID:
        """Record a state machine transition on any entity."""
        body = (
            f"Status changed from '{from_state}' → '{to_state}'."
            if from_state
            else f"Status set to '{to_state}'."
        )
        return await self._insert(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type="state_change",
            actor_id=actor_id,
            body=body,
            from_state=from_state,
            to_state=to_state,
            meta=meta or {},
        )

    async def write_stage_event(
        self,
        db:          AsyncSession,
        entity_type: str,
        entity_id:   uuid.UUID,
        actor_id:    uuid.UUID,
        body:        str,
        from_state:  Optional[str] = None,
        to_state:    Optional[str] = None,
        meta:        Optional[dict[str, Any]] = None,
    ) -> uuid.UUID:
        """Record a pipeline stage advancement, push-back, or completion."""
        return await self._insert(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type="stage_event",
            actor_id=actor_id,
            body=body,
            from_state=from_state,
            to_state=to_state,
            meta=meta or {},
        )

    # ── Query ────────────────────────────────────────────────

    async def get_entity_timeline(
        self,
        db:          AsyncSession,
        entity_type: str,
        entity_id:   uuid.UUID,
        page:        int = 1,
        size:        int = 50,
    ) -> dict:
        from sqlalchemy import func
        from app.modules.activity.models import ActivityTimeline

        base = (
            select(ActivityTimeline)
            .where(
                ActivityTimeline.entity_type == entity_type,
                ActivityTimeline.entity_id   == entity_id,
            )
        )
        total = (
            await db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        items = (
            await db.execute(
                base.order_by(ActivityTimeline.created_at.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        ).scalars().all()

        return {
            "items":       [self._serialize(e) for e in items],
            "total":       total,
            "page":        page,
            "size":        size,
            "total_pages": max(1, -(-total // size)),
        }

    # ── Internal ─────────────────────────────────────────────

    async def _insert(
        self,
        db:          AsyncSession,
        entity_type: str,
        entity_id:   uuid.UUID,
        event_type:  str,
        body:        Optional[str]       = None,
        actor_id:    Optional[uuid.UUID] = None,
        from_state:  Optional[str]       = None,
        to_state:    Optional[str]       = None,
        meta:        Optional[dict]      = None,
    ) -> uuid.UUID:
        import json

        tenant_id = tenant_id_ctx.get()
        if not tenant_id:
            raise ValueError("No tenant context — cannot write to activity_timeline.")

        row = (await db.execute(
            text("""
                INSERT INTO activity_timeline
                    (tenant_id, entity_type, entity_id, event_type,
                     actor_id, body, from_state, to_state, meta)
                VALUES
                    (:tenant_id, :entity_type, :entity_id, :event_type,
                     :actor_id, :body, :from_state, :to_state, CAST(:meta AS jsonb))
                RETURNING id
            """),
            {
                "tenant_id":   str(tenant_id),
                "entity_type": entity_type,
                "entity_id":   str(entity_id),
                "event_type":  event_type,
                "actor_id":    str(actor_id) if actor_id else None,
                "body":        body,
                "from_state":  from_state,
                "to_state":    to_state,
                "meta":        json.dumps(meta or {}),
            },
        )).fetchone()
        await db.flush()
        return row[0]

    @staticmethod
    def _serialize(e) -> dict:
        return {
            "id":          str(e.id),
            "entity_type": e.entity_type,
            "entity_id":   str(e.entity_id),
            "event_type":  e.event_type,
            "actor_id":    str(e.actor_id) if e.actor_id else None,
            "body":        e.body,
            "from_state":  e.from_state,
            "to_state":    e.to_state,
            "meta":        e.meta or {},
            "created_at":  e.created_at.isoformat(),
        }


timeline_writer = TimelineWriterService()
