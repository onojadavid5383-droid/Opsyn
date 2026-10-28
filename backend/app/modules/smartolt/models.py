# ============================================================
# OPSYN SMARTOLT MODELS — app/modules/smartolt/models.py
# ============================================================

from __future__ import annotations
import uuid, datetime
from typing import Any

from sqlalchemy import String, Boolean, Integer, Float, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SmartOLTConfig(Base):
    __tablename__      = "smartolt_config"
    __allow_unmapped__ = True

    id:                    Mapped[uuid.UUID]               = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:             Mapped[uuid.UUID]               = mapped_column(ForeignKey("tenants.id"), nullable=False, unique=True)
    api_key:               Mapped[str | None]              = mapped_column(String(255))
    api_url:               Mapped[str]                     = mapped_column(String(500), default="https://app.smartolt.com")
    webhook_secret:        Mapped[str | None]              = mapped_column(String(255))
    polling_enabled:       Mapped[bool]                    = mapped_column(Boolean, default=False)
    polling_interval_secs: Mapped[int]                     = mapped_column(Integer, default=60)
    severity_thresholds:   Mapped[dict[str, Any] | None]   = mapped_column(JSONB)
    created_at:            Mapped[datetime.datetime]       = mapped_column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    updated_at:            Mapped[datetime.datetime]       = mapped_column(DateTime(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class SmartOLTOltMap(Base):
    __tablename__      = "smartolt_olt_map"
    __allow_unmapped__ = True

    id:               Mapped[uuid.UUID]               = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:        Mapped[uuid.UUID]               = mapped_column(ForeignKey("tenants.id"), nullable=False)
    smartolt_olt_id:  Mapped[str]                     = mapped_column(String(100), nullable=False)
    olt_name:         Mapped[str | None]              = mapped_column(String(200))
    region_id:        Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("regions.id"))
    latitude:         Mapped[float | None]            = mapped_column(Float)
    longitude:        Mapped[float | None]            = mapped_column(Float)
    is_active:        Mapped[bool]                    = mapped_column(Boolean, default=True)
    last_synced_at:   Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
