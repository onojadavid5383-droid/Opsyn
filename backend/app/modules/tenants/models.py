# ============================================================
# OPSYN TENANT MODEL — app/modules/tenants/models.py
# SQLAlchemy ORM model for the tenants (subscriber) table.
# Every other table has tenant_id FK referencing this.
# ============================================================

from __future__ import annotations
import uuid
import datetime
from sqlalchemy import String, Boolean, Integer, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Tenant(Base):
    __tablename__      = "tenants"
    __allow_unmapped__ = True

    id:         Mapped[uuid.UUID]          = mapped_column(primary_key=True, default=uuid.uuid4)
    name:       Mapped[str]               = mapped_column(String(200), nullable=False)
    slug:       Mapped[str]               = mapped_column(String(80),  nullable=False, unique=True)
    plan:       Mapped[str]               = mapped_column(String(20),  nullable=False, default="starter")
    max_users:  Mapped[int]               = mapped_column(Integer,     nullable=False, default=50)
    is_active:  Mapped[bool]              = mapped_column(Boolean,     nullable=False, default=True)
    settings:   Mapped[dict]              = mapped_column(JSONB,       nullable=False, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.datetime.utcnow
    )
