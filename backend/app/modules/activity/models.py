# ============================================================
# OPSYN ACTIVITY TIMELINE MODEL — app/modules/activity/models.py
# ============================================================

from __future__ import annotations

import uuid
import datetime
from typing import Any

from sqlalchemy import String, Text, ForeignKey, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ActivityTimeline(Base):
    __tablename__      = "activity_timeline"
    __allow_unmapped__ = True

    id:          Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:   Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    entity_type: Mapped[str]                     = mapped_column(String(50),  nullable=False)
    entity_id:   Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type:  Mapped[str]                     = mapped_column(String(50),  nullable=False)
    actor_id:    Mapped[uuid.UUID | None]         = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    body:        Mapped[str | None]               = mapped_column(Text)
    from_state:  Mapped[str | None]               = mapped_column(String(30))
    to_state:    Mapped[str | None]               = mapped_column(String(30))
    meta:        Mapped[dict[str, Any] | None]    = mapped_column(JSONB, default=dict)
    created_at:  Mapped[datetime.datetime]        = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.datetime.utcnow
    )
