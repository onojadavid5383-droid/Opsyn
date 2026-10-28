# ============================================================
# OPSYN DESIGN MODELS — app/modules/design/models.py
#
# The design container (Network GIS plan §3.4, Phase 4). A design belongs
# to a project, has an optional boundary, its own uploaded inputs (roads,
# homepasses, poles… — decision D6) and numbered versions. Its WORKING SET
# is the net_assets / net_cables / net_connections rows with
# design_id = design.id; live network rows have design_id NULL.
#
# Schema, CHECKs and RLS: migration 0090.
# ============================================================

from __future__ import annotations

import datetime
import uuid
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, ForeignKey, Integer, LargeBinary, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

DESIGN_STATUSES: tuple[str, ...] = (
    "DRAFT", "GENERATED", "MODIFIED", "VALIDATING", "UNDER_REVIEW", "APPROVED",
    "REJECTED", "SUPERSEDED", "DEPLOYED",
)
# Statuses a person may set directly in Phase 4; review / approval /
# deployment move through their own workflows (Phases 9–10).
EDITABLE_STATUSES: tuple[str, ...] = ("DRAFT", "MODIFIED")
# While in review, approved, superseded or built, a design's content
# (boundary, inputs, engine config, working set) is frozen: 409 on change.
LOCKED_STATUSES: tuple[str, ...] = ("VALIDATING", "UNDER_REVIEW", "APPROVED", "SUPERSEDED", "DEPLOYED")

INPUT_LAYERS: tuple[str, ...] = ("road", "homepass", "pole", "building", "pickup", "existing_structure")


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _tenant() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)


def _user() -> Mapped[uuid.UUID | None]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))


def _now() -> Mapped[datetime.datetime]:
    return mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class Design(Base):
    __tablename__ = "designs"

    id:                 Mapped[uuid.UUID]              = _pk()
    tenant_id:          Mapped[uuid.UUID]              = _tenant()
    project_id:         Mapped[uuid.UUID]              = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name:               Mapped[str]                    = mapped_column(String(200), nullable=False)
    description:        Mapped[str | None]             = mapped_column(Text)
    boundary:           Mapped[Any | None]             = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=False))
    status:             Mapped[str]                    = mapped_column(String(20), nullable=False, default="DRAFT")
    current_version_id: Mapped[uuid.UUID | None]       = mapped_column(UUID(as_uuid=True))
    engine_config:      Mapped[dict[str, Any]]         = mapped_column(JSONB, nullable=False, default=dict)
    created_by:         Mapped[uuid.UUID | None]       = _user()
    updated_by:         Mapped[uuid.UUID | None]       = _user()
    created_at:         Mapped[datetime.datetime]      = _now()
    updated_at:         Mapped[datetime.datetime]      = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                                       server_default=text("now()"), onupdate=datetime.datetime.utcnow)
    deleted_at:         Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    deleted_by:         Mapped[uuid.UUID | None]       = _user()


class DesignInputUpload(Base):
    __tablename__ = "design_input_uploads"

    id:            Mapped[uuid.UUID]         = _pk()
    tenant_id:     Mapped[uuid.UUID]         = _tenant()
    design_id:     Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("designs.id", ondelete="CASCADE"), nullable=False)
    layer_key:     Mapped[str]               = mapped_column(String(30), nullable=False)
    filename:      Mapped[str | None]        = mapped_column(String(500))
    file_hash:     Mapped[str | None]        = mapped_column(String(64))
    feature_count: Mapped[int]               = mapped_column(Integer, nullable=False, default=0)
    mode:          Mapped[str]               = mapped_column(String(10), nullable=False, default="replace")
    uploaded_by:   Mapped[uuid.UUID | None]  = _user()
    uploaded_at:   Mapped[datetime.datetime] = _now()


class DesignInput(Base):
    __tablename__ = "design_inputs"

    id:         Mapped[uuid.UUID]         = _pk()
    tenant_id:  Mapped[uuid.UUID]         = _tenant()
    design_id:  Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("designs.id", ondelete="CASCADE"), nullable=False)
    layer_key:  Mapped[str]               = mapped_column(String(30), nullable=False)
    geom:       Mapped[Any]               = mapped_column(Geometry("GEOMETRY", srid=4326, spatial_index=False), nullable=False)
    properties: Mapped[dict[str, Any]]    = mapped_column(JSONB, nullable=False, default=dict)
    upload_id:  Mapped[uuid.UUID | None]  = mapped_column(UUID(as_uuid=True), ForeignKey("design_input_uploads.id", ondelete="SET NULL"))
    created_at: Mapped[datetime.datetime] = _now()


class DesignVersion(Base):
    __tablename__ = "design_versions"

    id:                 Mapped[uuid.UUID]              = _pk()
    tenant_id:          Mapped[uuid.UUID]              = _tenant()
    design_id:          Mapped[uuid.UUID]              = mapped_column(UUID(as_uuid=True), ForeignKey("designs.id", ondelete="CASCADE"), nullable=False)
    version_no:         Mapped[int]                    = mapped_column(Integer, nullable=False)
    parent_version_id:  Mapped[uuid.UUID | None]       = mapped_column(UUID(as_uuid=True), ForeignKey("design_versions.id", ondelete="SET NULL"))
    creation_method:    Mapped[str]                    = mapped_column(String(20), nullable=False, default="INITIAL")
    label:              Mapped[str | None]             = mapped_column(String(200))
    snapshot:           Mapped[bytes | None]           = mapped_column(LargeBinary)
    boq_snapshot:       Mapped[dict[str, Any] | None]  = mapped_column(JSONB)
    validation_summary: Mapped[dict[str, Any] | None]  = mapped_column(JSONB)
    optical_summary:    Mapped[dict[str, Any] | None]  = mapped_column(JSONB)
    # Phase 8 (0092): set when the snapshot is taken — the version is then immutable
    snapshot_counts:    Mapped[dict[str, Any] | None]  = mapped_column(JSONB)
    frozen_at:          Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_by:         Mapped[uuid.UUID | None]       = _user()
    created_at:         Mapped[datetime.datetime]      = _now()


class DesignValidationIssue(Base):
    __tablename__ = "design_validation_issues"

    id:         Mapped[uuid.UUID]              = _pk()
    tenant_id:  Mapped[uuid.UUID]              = _tenant()
    design_id:  Mapped[uuid.UUID]              = mapped_column(UUID(as_uuid=True), ForeignKey("designs.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[uuid.UUID | None]       = mapped_column(UUID(as_uuid=True), ForeignKey("design_versions.id", ondelete="SET NULL"))
    severity:   Mapped[str]                    = mapped_column(String(10), nullable=False)
    code:       Mapped[str]                    = mapped_column(String(60), nullable=False)
    rule:       Mapped[str | None]             = mapped_column(String(200))
    message:    Mapped[str]                    = mapped_column(Text, nullable=False)
    asset_id:   Mapped[uuid.UUID | None]       = mapped_column(UUID(as_uuid=True))
    cable_id:   Mapped[uuid.UUID | None]       = mapped_column(UUID(as_uuid=True))
    geom:       Mapped[Any | None]             = mapped_column(Geometry("GEOMETRY", srid=4326, spatial_index=False))
    # "metadata" is reserved on declarative models; the column keeps its name
    meta:       Mapped[dict[str, Any]]         = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime.datetime]      = _now()


class DesignOperation(Base):
    """Edit operation log with inverses — written from Phase 6."""
    __tablename__ = "design_operations"

    id:         Mapped[uuid.UUID]               = _pk()
    tenant_id:  Mapped[uuid.UUID]               = _tenant()
    design_id:  Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), ForeignKey("designs.id", ondelete="CASCADE"), nullable=False)
    seq:        Mapped[int]                     = mapped_column(BigInteger, nullable=False)
    op:         Mapped[str]                     = mapped_column(String(30), nullable=False)
    payload:    Mapped[dict[str, Any]]          = mapped_column(JSONB, nullable=False, default=dict)
    inverse:    Mapped[dict[str, Any] | None]   = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None]        = _user()
    created_at: Mapped[datetime.datetime]       = _now()
    undone_at:  Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
