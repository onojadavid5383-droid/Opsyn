# ============================================================
# OPSYN SHIFT MODELS — app/modules/shifts/models.py
# ============================================================

from __future__ import annotations
import uuid, datetime
from sqlalchemy import String, Text, Boolean, Integer, Date, Time, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Shift(Base):
    __tablename__      = "shifts"
    __allow_unmapped__ = True

    id:         Mapped[uuid.UUID]               = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:  Mapped[uuid.UUID]               = mapped_column(ForeignKey("tenants.id"), nullable=False)
    name:       Mapped[str]                     = mapped_column(String(100), nullable=False)
    shift_type: Mapped[str]                     = mapped_column(String(30), default="day")
    start_time: Mapped[datetime.time]           = mapped_column(Time, nullable=False)
    end_time:   Mapped[datetime.time]           = mapped_column(Time, nullable=False)
    color:      Mapped[str]                     = mapped_column(String(20), default="#06b6d4")
    created_by: Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime]       = mapped_column(DateTime(timezone=True), default=datetime.datetime.utcnow)


class ShiftAssignment(Base):
    __tablename__      = "shift_assignments"
    __allow_unmapped__ = True

    id:         Mapped[uuid.UUID]               = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:  Mapped[uuid.UUID]               = mapped_column(ForeignKey("tenants.id"), nullable=False)
    shift_id:   Mapped[uuid.UUID]               = mapped_column(ForeignKey("shifts.id"), nullable=False)
    user_id:    Mapped[uuid.UUID]               = mapped_column(ForeignKey("users.id"), nullable=False)
    date:       Mapped[datetime.date]           = mapped_column(Date, nullable=False)
    status:     Mapped[str]                     = mapped_column(String(20), default="scheduled")
    notes:      Mapped[str | None]              = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime]       = mapped_column(DateTime(timezone=True), default=datetime.datetime.utcnow)


class ShiftSwapRequest(Base):
    __tablename__      = "shift_swap_requests"
    __allow_unmapped__ = True

    id:                 Mapped[uuid.UUID]               = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:          Mapped[uuid.UUID]               = mapped_column(ForeignKey("tenants.id"), nullable=False)
    from_assignment_id: Mapped[uuid.UUID]               = mapped_column(ForeignKey("shift_assignments.id"), nullable=False)
    to_user_id:         Mapped[uuid.UUID]               = mapped_column(ForeignKey("users.id"), nullable=False)
    reason:             Mapped[str | None]              = mapped_column(Text)
    status:             Mapped[str]                     = mapped_column(String(20), default="pending")
    responded_by:       Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("users.id"))
    responded_at:       Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_by:         Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("users.id"))
    created_at:         Mapped[datetime.datetime]       = mapped_column(DateTime(timezone=True), default=datetime.datetime.utcnow)


class OutageNotificationRule(Base):
    __tablename__      = "outage_notification_rules"
    __allow_unmapped__ = True

    id:               Mapped[uuid.UUID]               = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:        Mapped[uuid.UUID]               = mapped_column(ForeignKey("tenants.id"), nullable=False)
    name:             Mapped[str]                     = mapped_column(String(200), nullable=False)
    min_severity:     Mapped[str]                     = mapped_column(String(20), default="warning")
    min_subscribers:  Mapped[int]                     = mapped_column(Integer, default=0)
    channels:         Mapped[list | None]             = mapped_column(JSONB)
    message_template: Mapped[str | None]              = mapped_column(Text)
    is_auto:          Mapped[bool]                    = mapped_column(Boolean, default=False)
    is_active:        Mapped[bool]                    = mapped_column(Boolean, default=True)
    created_by:       Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("users.id"))
    created_at:       Mapped[datetime.datetime]       = mapped_column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    updated_at:       Mapped[datetime.datetime]       = mapped_column(DateTime(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class OutageNotificationLog(Base):
    __tablename__      = "outage_notification_log"
    __allow_unmapped__ = True

    id:            Mapped[uuid.UUID]               = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:     Mapped[uuid.UUID]               = mapped_column(ForeignKey("tenants.id"), nullable=False)
    outage_id:     Mapped[uuid.UUID]               = mapped_column(ForeignKey("outage_incidents.id"), nullable=False)
    rule_id:       Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("outage_notification_rules.id"))
    channel:       Mapped[str | None]              = mapped_column(String(20))
    recipient:     Mapped[str | None]              = mapped_column(String(255))
    status:        Mapped[str]                     = mapped_column(String(20), default="sent")
    error_message: Mapped[str | None]              = mapped_column(Text)
    sent_at:       Mapped[datetime.datetime]       = mapped_column(DateTime(timezone=True), default=datetime.datetime.utcnow)
