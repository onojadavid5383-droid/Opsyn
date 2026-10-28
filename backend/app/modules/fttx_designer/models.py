# ============================================================
# OPSYN FTTX DESIGNER MODELS — app/modules/fttx_designer/models.py
# Backs alembic/versions/0085_fttx_designer_runs.py — see that
# migration's docstring for the full schema rationale.
# ============================================================

from __future__ import annotations

import uuid
import datetime
from typing import Any

from sqlalchemy import String, Text, Integer, ForeignKey, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class FttxDesignRun(Base):
    __tablename__      = "fttx_design_runs"
    __allow_unmapped__ = True

    id:               Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:        Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name:             Mapped[str | None]          = mapped_column(String(200))
    # draft | layers_pending | ready | queued | running | completed | failed | cancelled
    status:           Mapped[str]                 = mapped_column(String(20), nullable=False, default="draft")
    config:           Mapped[dict[str, Any]]      = mapped_column(JSONB, nullable=False, default=dict)
    progress_pct:     Mapped[int]                 = mapped_column(Integer, nullable=False, default=0)
    progress_message: Mapped[str | None]          = mapped_column(String(200))
    error_message:    Mapped[str | None]          = mapped_column(Text)
    # Failed pipelines do not produce an output row, but their diagnostic log
    # must remain downloadable from the run record.
    log_text:         Mapped[str | None]          = mapped_column(Text)
    celery_task_id:   Mapped[str | None]          = mapped_column(String(100))
    result_summary:   Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Network GIS Phase 5 (migration 0091): the design this run was made for,
    # and the design version its output became
    design_id:        Mapped[uuid.UUID | None]    = mapped_column(UUID(as_uuid=True), ForeignKey("designs.id", ondelete="SET NULL"), nullable=True)
    design_version_id: Mapped[uuid.UUID | None]   = mapped_column(UUID(as_uuid=True), ForeignKey("design_versions.id", ondelete="SET NULL"), nullable=True)
    created_by:       Mapped[uuid.UUID | None]    = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at:       Mapped[datetime.datetime]   = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)
    updated_at:       Mapped[datetime.datetime]   = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    started_at:       Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at:     Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    layers: Mapped[list["FttxDesignRunLayer"]] = relationship(
        "FttxDesignRunLayer", back_populates="run", lazy="select", cascade="all, delete-orphan",
    )
    output: Mapped["FttxDesignRunOutput | None"] = relationship(
        "FttxDesignRunOutput", back_populates="run", lazy="select", uselist=False,
        cascade="all, delete-orphan",
    )


class FttxDesignRunLayer(Base):
    __tablename__      = "fttx_design_run_layers"
    __allow_unmapped__ = True

    id:                Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id:            Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("fttx_design_runs.id", ondelete="CASCADE"), nullable=False)
    tenant_id:         Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    # 'road' | 'homepass' | 'pole' | 'building' | 'pickup'
    layer_key:         Mapped[str]               = mapped_column(String(20), nullable=False)
    original_filename: Mapped[str | None]        = mapped_column(String(500))
    feature_count:     Mapped[int | None]        = mapped_column(Integer)
    geojson:           Mapped[dict[str, Any]]    = mapped_column(JSONB, nullable=False)
    uploaded_by:       Mapped[uuid.UUID | None]  = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploaded_at:       Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)

    run: Mapped["FttxDesignRun"] = relationship("FttxDesignRun", back_populates="layers")


class FttxDesignRunOutput(Base):
    __tablename__      = "fttx_design_run_outputs"
    __allow_unmapped__ = True

    id:                    Mapped[uuid.UUID]             = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id:                Mapped[uuid.UUID]             = mapped_column(UUID(as_uuid=True), ForeignKey("fttx_design_runs.id", ondelete="CASCADE"), nullable=False)
    tenant_id:             Mapped[uuid.UUID]             = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    output_layers:         Mapped[dict[str, Any]]        = mapped_column(JSONB, nullable=False)
    boq_rows:              Mapped[list[Any] | None]      = mapped_column(JSONB)
    boq_fdt_rows:          Mapped[list[Any] | None]      = mapped_column(JSONB)
    optical_loss_summary:  Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    project_identity:      Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    log_text:              Mapped[str | None]            = mapped_column(Text)
    created_at:            Mapped[datetime.datetime]     = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)

    run: Mapped["FttxDesignRun"] = relationship("FttxDesignRun", back_populates="output")
