from __future__ import annotations
import uuid
import datetime
from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class WebhookApiKey(Base):
    __tablename__      = "webhook_api_keys"
    __allow_unmapped__ = True

    id:         Mapped[uuid.UUID]         = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:  Mapped[uuid.UUID]         = mapped_column(ForeignKey("tenants.id"), nullable=False)
    app_name:   Mapped[str]               = mapped_column(String(100), nullable=False)
    secret_key: Mapped[str]               = mapped_column(String(255), nullable=False)
    is_active:  Mapped[bool]              = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None]  = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(default=datetime.datetime.utcnow)
