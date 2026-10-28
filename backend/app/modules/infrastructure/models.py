# ============================================================
# OPSYN INFRASTRUCTURE MODELS — app/modules/infrastructure/models.py
# ============================================================

from __future__ import annotations

import uuid
import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import String, Text, Integer, SmallInteger, Numeric, Date, ForeignKey, TIMESTAMP, Boolean, Double
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from geoalchemy2 import Geometry  # Required dependency for PostGIS support

from app.core.database import Base
from app.modules.tasks.models import Task  # noqa: F401 — registers tasks table so InfraCapacityAlert FK resolves


class InfrastructureSite(Base):
    __tablename__      = "infrastructure_sites"
    __allow_unmapped__ = True

    id:         Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:  Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name:       Mapped[str]                = mapped_column(String(200), nullable=False)
    site_type:  Mapped[str]                = mapped_column(String(30),  nullable=False, default="POP")
    address:    Mapped[str | None]         = mapped_column(Text)
    latitude:   Mapped[Decimal | None]     = mapped_column(Numeric(10, 7))
    longitude:  Mapped[Decimal | None]     = mapped_column(Numeric(10, 7))
    region_id:  Mapped[uuid.UUID | None]   = mapped_column(UUID(as_uuid=True), ForeignKey("regions.id", ondelete="SET NULL"), nullable=True)
    status:     Mapped[str]                = mapped_column(String(20),  nullable=False, default="active")
    notes:      Mapped[str | None]         = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None]   = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime.datetime]  = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)
    updated_at: Mapped[datetime.datetime]  = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    nodes: Mapped[list["InfrastructureNode"]] = relationship("InfrastructureNode", back_populates="site", lazy="select")


class InfrastructureNode(Base):
    __tablename__      = "infrastructure_nodes"
    __allow_unmapped__ = True

    id:           Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:    Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    site_id:      Mapped[uuid.UUID | None]  = mapped_column(UUID(as_uuid=True), ForeignKey("infrastructure_sites.id", ondelete="SET NULL"), nullable=True)
    name:         Mapped[str]               = mapped_column(String(200), nullable=False)
    node_type:    Mapped[str]               = mapped_column(String(30),  nullable=False, default="OLT")
    manufacturer: Mapped[str | None]        = mapped_column(String(100))
    model:        Mapped[str | None]        = mapped_column(String(100))
    ip_address:   Mapped[str | None]        = mapped_column(String(45))
    port_count:   Mapped[int | None]        = mapped_column(Integer)
    status:       Mapped[str]               = mapped_column(String(20),  nullable=False, default="active")
    meta:         Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    created_by:   Mapped[uuid.UUID | None]  = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at:   Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)
    updated_at:   Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    site: Mapped["InfrastructureSite | None"] = relationship("InfrastructureSite", back_populates="nodes")


class InfrastructureRoute(Base):
    __tablename__      = "infrastructure_routes"
    __allow_unmapped__ = True

    id:             Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:      Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    from_node_id:   Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("infrastructure_nodes.id", ondelete="CASCADE"), nullable=False)
    to_node_id:     Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("infrastructure_nodes.id", ondelete="CASCADE"), nullable=False)
    cable_type:     Mapped[str | None]         = mapped_column(String(50))
    length_km:      Mapped[Decimal | None]     = mapped_column(Numeric(8, 3))
    capacity_gbps:  Mapped[Decimal | None]     = mapped_column(Numeric(8, 2))
    status:         Mapped[str]                = mapped_column(String(20),  nullable=False, default="active")
    installed_at:   Mapped[datetime.date | None] = mapped_column(Date)
    notes:          Mapped[str | None]         = mapped_column(Text)
    created_by:     Mapped[uuid.UUID | None]   = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at:     Mapped[datetime.datetime]  = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)


# ── S4.1 additions ────────────────────────────────────────────

class InfraPort(Base):
    __tablename__      = "infra_ports"
    __allow_unmapped__ = True

    id:             Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:      Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    node_id:        Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("infrastructure_nodes.id", ondelete="CASCADE"), nullable=False)
    port_number:    Mapped[str]               = mapped_column(String(20),  nullable=False)
    port_type:      Mapped[str]               = mapped_column(String(30),  nullable=False, default="GPON")
    total_capacity: Mapped[int]               = mapped_column(Integer, nullable=False, default=128)
    used_capacity:  Mapped[int]               = mapped_column(Integer, nullable=False, default=0)
    status:         Mapped[str]               = mapped_column(String(20),  nullable=False, default="active")
    last_synced_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at:     Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)
    updated_at:     Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class InfraSubscriber(Base):
    __tablename__      = "infra_subscribers"
    __allow_unmapped__ = True

    id:           Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:    Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    customer_id:  Mapped[str]               = mapped_column(String(100), nullable=False)
    site_id:      Mapped[uuid.UUID | None]  = mapped_column(UUID(as_uuid=True), ForeignKey("infrastructure_sites.id", ondelete="SET NULL"), nullable=True)
    node_id:      Mapped[uuid.UUID | None]  = mapped_column(UUID(as_uuid=True), ForeignKey("infrastructure_nodes.id", ondelete="SET NULL"), nullable=True)
    port_id:      Mapped[uuid.UUID | None]  = mapped_column(UUID(as_uuid=True), ForeignKey("infra_ports.id", ondelete="SET NULL"), nullable=True)
    service_type: Mapped[str]               = mapped_column(String(50),  nullable=False, default="FTTH")
    status:       Mapped[str]               = mapped_column(String(20),  nullable=False, default="active")
    address:      Mapped[str | None]        = mapped_column(Text)
    latitude:     Mapped[Decimal | None]    = mapped_column(Numeric(10, 7))
    longitude:    Mapped[Decimal | None]    = mapped_column(Numeric(10, 7))
    created_at:   Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)
    updated_at:   Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class InfraCapacityAlert(Base):
    __tablename__      = "infra_capacity_alerts"
    __allow_unmapped__ = True

    id:             Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:      Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    site_id:        Mapped[uuid.UUID | None]    = mapped_column(UUID(as_uuid=True), ForeignKey("infrastructure_sites.id", ondelete="SET NULL"), nullable=True)
    node_id:        Mapped[uuid.UUID | None]    = mapped_column(UUID(as_uuid=True), ForeignKey("infrastructure_nodes.id", ondelete="SET NULL"), nullable=True)
    alert_type:     Mapped[str]                 = mapped_column(String(30), nullable=False, default="capacity")
    severity:       Mapped[str]                 = mapped_column(String(20), nullable=False, default="warning")
    threshold_pct:  Mapped[int]                 = mapped_column(Integer, nullable=False)
    current_pct:    Mapped[int]                 = mapped_column(Integer, nullable=False)
    message:        Mapped[str | None]          = mapped_column(Text)
    is_resolved:    Mapped[bool]                = mapped_column(nullable=False, default=False)
    resolved_at:    Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    linked_task_id: Mapped[uuid.UUID | None]    = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    created_at:     Mapped[datetime.datetime]   = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)


class InfraMonitoringConfig(Base):
    __tablename__      = "infra_monitoring_config"
    __allow_unmapped__ = True

    id:                     Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:              Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    entity_type:            Mapped[str]               = mapped_column(String(30), nullable=False)
    entity_id:              Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), nullable=False)
    warn_threshold_pct:     Mapped[int]               = mapped_column(Integer, nullable=False, default=70)
    critical_threshold_pct: Mapped[int]               = mapped_column(Integer, nullable=False, default=90)
    check_interval_minutes: Mapped[int]               = mapped_column(Integer, nullable=False, default=15)
    alert_channels:         Mapped[list[Any] | None]  = mapped_column(JSONB, default=list)
    assigned_role_level:    Mapped[int]               = mapped_column(Integer, nullable=False, default=2)
    is_active:              Mapped[bool]              = mapped_column(nullable=False, default=True)
    created_at:             Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)
    updated_at:             Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class InfraAlertRule(Base):
    __tablename__      = "infra_alert_rules"
    __allow_unmapped__ = True

    id:              Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:       Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name:            Mapped[str]                 = mapped_column(String(200), nullable=False)
    condition_field: Mapped[str]                 = mapped_column(String(50),  nullable=False)
    operator:        Mapped[str]                 = mapped_column(String(10),  nullable=False, default="gt")
    threshold_value: Mapped[Decimal]             = mapped_column(Numeric(10, 2), nullable=False)
    severity:        Mapped[str]                 = mapped_column(String(20),  nullable=False, default="warning")
    action_type:     Mapped[str]                 = mapped_column(String(30),  nullable=False, default="notify")
    action_params:   Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    is_active:       Mapped[bool]                = mapped_column(nullable=False, default=True)
    created_at:      Mapped[datetime.datetime]   = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# FTTH Asset Management — Phase 1 ORM Models
# ══════════════════════════════════════════════════════════════

# Geometry column type — PostGIS Point with SRID 4326 (WGS84)
_PointGeom = Geometry("POINT", srid=4326)


class InfraUploadSession(Base):
    """Tracks every upload attempt for FTTH assets (splitter/cabinet/olt/cable_route)."""
    __tablename__      = "infrastructure_upload_sessions"
    __allow_unmapped__ = True

    id:                Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:         Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    asset_type:        Mapped[str]                     = mapped_column(String(30), nullable=False)
    status:            Mapped[str]                     = mapped_column(String(20), nullable=False, default="pending")
    original_filename: Mapped[str | None]              = mapped_column(String(500))
    file_hash:         Mapped[str | None]              = mapped_column(String(64))
    total_rows:        Mapped[int | None]              = mapped_column(Integer)
    valid_rows:        Mapped[int | None]              = mapped_column(Integer)
    duplicate_rows:    Mapped[int | None]              = mapped_column(Integer)
    error_rows:        Mapped[int | None]              = mapped_column(Integer)
    committed_rows:    Mapped[int | None]              = mapped_column(Integer)
    validation_errors: Mapped[list[Any] | None]        = mapped_column(JSONB, default=list)
    submitted_by:      Mapped[uuid.UUID | None]        = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    approved_by:       Mapped[uuid.UUID | None]        = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at:      Mapped[datetime.datetime]       = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)
    approved_at:       Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    committed_at:      Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    staging_rows: Mapped[list["InfraUploadStaging"]] = relationship(
        "InfraUploadStaging", back_populates="session", lazy="select"
    )


class InfraDeletionSession(Base):
    """Tracks every batch deletion attempt for FTTH assets."""
    __tablename__      = "infrastructure_deletion_sessions"
    __allow_unmapped__ = True

    id:                Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:         Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    asset_type:        Mapped[str]                     = mapped_column(String(30), nullable=False)
    status:            Mapped[str]                     = mapped_column(String(20), nullable=False, default="pending")
    original_filename: Mapped[str | None]              = mapped_column(String(500))
    total_rows:        Mapped[int | None]              = mapped_column(Integer)
    matched_rows:      Mapped[int | None]              = mapped_column(Integer)
    unmatched_rows:    Mapped[int | None]              = mapped_column(Integer)
    deleted_rows:      Mapped[int | None]              = mapped_column(Integer)
    cascaded_rows:     Mapped[int]                     = mapped_column(Integer, nullable=False, default=0)
    cascade_preview:   Mapped[list[Any]]               = mapped_column(JSONB, default=list)
    match_details:     Mapped[list[Any] | None]        = mapped_column(JSONB, default=list)
    submitted_by:      Mapped[uuid.UUID | None]        = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    approved_by:       Mapped[uuid.UUID | None]        = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at:      Mapped[datetime.datetime]       = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)
    approved_at:       Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    executed_at:       Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class Cabinet(Base):
    """FTTH cabinet (ODF / splice box) with PostGIS Point location."""
    __tablename__      = "cabinets"
    __allow_unmapped__ = True

    id:                Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:         Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    cabinet_id:        Mapped[str]                     = mapped_column(String(100), nullable=False)
    capacity:          Mapped[int]                     = mapped_column(Integer, nullable=False)
    number_tray:       Mapped[int]                     = mapped_column(SmallInteger, nullable=False)
    longitude:         Mapped[float]                   = mapped_column(Double(precision=53), nullable=False)
    latitude:          Mapped[float]                   = mapped_column(Double(precision=53), nullable=False)
    location:          Mapped[Any]                     = mapped_column(_PointGeom, nullable=False)
    custom_data:       Mapped[dict[str, Any]]          = mapped_column(JSONB, nullable=False, default=dict)
    is_deleted:        Mapped[bool]                    = mapped_column(Boolean, nullable=False, default=False)
    created_by:        Mapped[uuid.UUID | None]        = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    upload_session_id: Mapped[uuid.UUID | None]        = mapped_column(UUID(as_uuid=True), ForeignKey("infrastructure_upload_sessions.id", ondelete="SET NULL"))
    created_at:        Mapped[datetime.datetime]       = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)
    updated_at:        Mapped[datetime.datetime]       = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    splitters: Mapped[list["SplitterBox"]] = relationship(
        "SplitterBox", back_populates="cabinet", lazy="select"
    )


class OLT(Base):
    """Optical Line Terminal with PostGIS Point location."""
    __tablename__      = "olts"
    __allow_unmapped__ = True

    id:                   Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:            Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name:                 Mapped[str]                     = mapped_column(String(200), nullable=False)
    location_description: Mapped[str]                     = mapped_column(Text, nullable=False)
    number_of_odf:        Mapped[int | None]              = mapped_column(SmallInteger)
    longitude:            Mapped[float]                   = mapped_column(Double(precision=53), nullable=False)
    latitude:             Mapped[float]                   = mapped_column(Double(precision=53), nullable=False)
    location:             Mapped[Any]                     = mapped_column(_PointGeom, nullable=False)
    custom_data:          Mapped[dict[str, Any]]          = mapped_column(JSONB, nullable=False, default=dict)
    is_deleted:           Mapped[bool]                    = mapped_column(Boolean, nullable=False, default=False)
    created_by:           Mapped[uuid.UUID | None]        = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    upload_session_id:    Mapped[uuid.UUID | None]        = mapped_column(UUID(as_uuid=True), ForeignKey("infrastructure_upload_sessions.id", ondelete="SET NULL"))
    created_at:           Mapped[datetime.datetime]       = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)
    updated_at:           Mapped[datetime.datetime]       = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class SplitterBox(Base):
    """FTTH splitter box — First-Level or Second-Level, self-referential hierarchy."""
    __tablename__      = "splitter_boxes"
    __allow_unmapped__ = True

    id:                Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:         Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    box_id:            Mapped[str]                     = mapped_column(String(100), nullable=False)
    input_ports:       Mapped[int]                     = mapped_column(SmallInteger, nullable=False)
    output_ports:      Mapped[int]                     = mapped_column(SmallInteger, nullable=False)
    splitter_level:    Mapped[str]                     = mapped_column(String(20), nullable=False)
    splitter_type:     Mapped[str]                     = mapped_column(String(20), nullable=False)
    number_customer:   Mapped[int | None]              = mapped_column(Integer)
    longitude:         Mapped[float]                   = mapped_column(Double(precision=53), nullable=False)
    latitude:          Mapped[float]                   = mapped_column(Double(precision=53), nullable=False)
    location:          Mapped[Any]                     = mapped_column(_PointGeom, nullable=False)
    custom_data:       Mapped[dict[str, Any]]          = mapped_column(JSONB, nullable=False, default=dict)
    parent_splitter_id: Mapped[uuid.UUID | None]       = mapped_column(UUID(as_uuid=True), ForeignKey("splitter_boxes.id", ondelete="SET NULL"))
    cabinet_id:        Mapped[uuid.UUID | None]        = mapped_column(UUID(as_uuid=True), ForeignKey("cabinets.id", ondelete="SET NULL"))
    is_deleted:        Mapped[bool]                    = mapped_column(Boolean, nullable=False, default=False)
    created_by:        Mapped[uuid.UUID | None]        = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    upload_session_id: Mapped[uuid.UUID | None]        = mapped_column(UUID(as_uuid=True), ForeignKey("infrastructure_upload_sessions.id", ondelete="SET NULL"))
    created_at:        Mapped[datetime.datetime]       = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)
    updated_at:        Mapped[datetime.datetime]       = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    cabinet: Mapped["Cabinet | None"] = relationship("Cabinet", back_populates="splitters")
    parent:  Mapped["SplitterBox | None"] = relationship(
        "SplitterBox", remote_side="SplitterBox.id", foreign_keys=[parent_splitter_id], lazy="select"
    )


class InfraUploadStaging(Base):
    """Staging rows written during validation; moved to live tables on commit."""
    __tablename__      = "infrastructure_upload_staging"
    __allow_unmapped__ = True

    id:           Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id:   Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("infrastructure_upload_sessions.id", ondelete="CASCADE"), nullable=False)
    tenant_id:    Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), nullable=False)
    asset_type:   Mapped[str]                = mapped_column(String(30), nullable=False)
    row_number:   Mapped[int]                = mapped_column(Integer, nullable=False)
    row_data:     Mapped[dict[str, Any]]     = mapped_column(JSONB, nullable=False, default=dict)
    is_valid:     Mapped[bool]               = mapped_column(Boolean, nullable=False, default=False)
    is_duplicate: Mapped[bool]               = mapped_column(Boolean, nullable=False, default=False)
    errors:       Mapped[list[Any] | None]   = mapped_column(JSONB, default=list)
    committed:    Mapped[bool]               = mapped_column(Boolean, nullable=False, default=False)

    session: Mapped["InfraUploadSession"] = relationship("InfraUploadSession", back_populates="staging_rows")


class InfraAuditLog(Base):
    """Full audit trail for every upload, deletion, and restore on FTTH assets."""
    __tablename__      = "infrastructure_audit_log"
    __allow_unmapped__ = True

    id:          Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id:   Mapped[uuid.UUID]               = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    asset_type:  Mapped[str]                     = mapped_column(String(30), nullable=False)
    asset_id:    Mapped[uuid.UUID | None]        = mapped_column(UUID(as_uuid=True))
    asset_key:   Mapped[str | None]              = mapped_column(String(200))
    action:      Mapped[str]                     = mapped_column(String(30), nullable=False)
    session_id:  Mapped[uuid.UUID | None]        = mapped_column(UUID(as_uuid=True))
    actor_id:    Mapped[uuid.UUID | None]        = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    actor_label: Mapped[str | None]              = mapped_column(String(200))
    timestamp:   Mapped[datetime.datetime]       = mapped_column(TIMESTAMP(timezone=True), default=datetime.datetime.utcnow)
    old_data:    Mapped[dict[str, Any] | None]   = mapped_column(JSONB)
    new_data:    Mapped[dict[str, Any] | None]   = mapped_column(JSONB)
