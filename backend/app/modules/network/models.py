# ============================================================
# OPSYN NETWORK MODELS — app/modules/network/models.py
#
# The unified network model (Network GIS plan §3.1–3.2). PostGIS is the
# source of truth for every piece of physical plant:
#
#   net_assets   one row per point-like asset (POP … CUSTOMER_ENDPOINT)
#   net_cables   one row per cable, with a real LineString geometry
#   net_ports    ports on an asset (PON, splitter in/out, FAT out, …)
#
# design_id NULL = live network; a value = that design's working set
# (the designs table arrives in Phase 4, which adds the foreign key).
# Nothing is hard-deleted: deleted_at/deleted_by mark a soft delete.
#
# Schema, CHECK constraints, indexes and RLS live in migration 0087.
# The legacy infrastructure_sites/nodes/routes tables are untouched and
# keep serving their existing consumers (decision D4, revised 2026-09-25).
# ============================================================

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _tenant() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)


def _user_fk() -> Mapped[uuid.UUID | None]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def _created_at() -> Mapped[datetime.datetime]:
    return mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class NetAsset(Base):
    __tablename__ = "net_assets"

    id:               Mapped[uuid.UUID]              = _uuid_pk()
    tenant_id:        Mapped[uuid.UUID]              = _tenant()
    asset_code:       Mapped[str]                    = mapped_column(String(100), nullable=False)
    asset_type:       Mapped[str]                    = mapped_column(String(30), nullable=False)
    name:             Mapped[str | None]             = mapped_column(String(200))
    description:      Mapped[str | None]             = mapped_column(Text)
    geom:             Mapped[Any]                    = mapped_column(Geometry("GEOMETRY", srid=4326, spatial_index=False), nullable=False)
    lifecycle_status: Mapped[str]                    = mapped_column(String(20), nullable=False, default="PLANNED")
    creation_method:  Mapped[str]                    = mapped_column(String(20), nullable=False, default="MANUAL")
    parent_id:        Mapped[uuid.UUID | None]       = mapped_column(UUID(as_uuid=True), ForeignKey("net_assets.id", ondelete="SET NULL"))
    project_id:       Mapped[uuid.UUID | None]       = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"))
    design_id:        Mapped[uuid.UUID | None]       = mapped_column(UUID(as_uuid=True))
    lineage_id:       Mapped[uuid.UUID]              = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    attributes:       Mapped[dict[str, Any]]         = mapped_column(JSONB, nullable=False, default=dict)
    capacity:         Mapped[int | None]             = mapped_column(Integer)
    used_capacity:    Mapped[int | None]             = mapped_column(Integer)
    source_table:     Mapped[str | None]             = mapped_column(String(50))
    source_id:        Mapped[uuid.UUID | None]       = mapped_column(UUID(as_uuid=True))
    created_by:       Mapped[uuid.UUID | None]       = _user_fk()
    updated_by:       Mapped[uuid.UUID | None]       = _user_fk()
    created_at:       Mapped[datetime.datetime]      = _created_at()
    updated_at:       Mapped[datetime.datetime]      = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                                     server_default=text("now()"), onupdate=datetime.datetime.utcnow)
    deleted_at:       Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    deleted_by:       Mapped[uuid.UUID | None]       = _user_fk()


class NetCable(Base):
    __tablename__ = "net_cables"

    id:                Mapped[uuid.UUID]              = _uuid_pk()
    tenant_id:         Mapped[uuid.UUID]              = _tenant()
    asset_code:        Mapped[str]                    = mapped_column(String(100), nullable=False)
    cable_category:    Mapped[str]                    = mapped_column(String(20), nullable=False)
    name:              Mapped[str | None]             = mapped_column(String(200))
    description:       Mapped[str | None]             = mapped_column(Text)
    geom:              Mapped[Any]                    = mapped_column(Geometry("LINESTRING", srid=4326, spatial_index=False), nullable=False)
    design_geom:       Mapped[Any | None]             = mapped_column(Geometry("LINESTRING", srid=4326, spatial_index=False))
    asbuilt_geom:      Mapped[Any | None]             = mapped_column(Geometry("LINESTRING", srid=4326, spatial_index=False))
    fiber_count:       Mapped[int | None]             = mapped_column(Integer)
    # Set by the net_cables_length trigger from ST_Length(geom::geography).
    length_m:          Mapped[Decimal | None]         = mapped_column(Numeric(12, 2))
    installation_type: Mapped[str | None]             = mapped_column(String(20))
    route_method:      Mapped[str]                    = mapped_column(String(20), nullable=False, default="ROAD_GRAPH")
    source_asset_id:   Mapped[uuid.UUID | None]       = mapped_column(UUID(as_uuid=True), ForeignKey("net_assets.id", ondelete="SET NULL"))
    dest_asset_id:     Mapped[uuid.UUID | None]       = mapped_column(UUID(as_uuid=True), ForeignKey("net_assets.id", ondelete="SET NULL"))
    lifecycle_status:  Mapped[str]                    = mapped_column(String(20), nullable=False, default="PLANNED")
    creation_method:   Mapped[str]                    = mapped_column(String(20), nullable=False, default="MANUAL")
    project_id:        Mapped[uuid.UUID | None]       = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"))
    design_id:         Mapped[uuid.UUID | None]       = mapped_column(UUID(as_uuid=True))
    lineage_id:        Mapped[uuid.UUID]              = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    attributes:        Mapped[dict[str, Any]]         = mapped_column(JSONB, nullable=False, default=dict)
    source_table:      Mapped[str | None]             = mapped_column(String(50))
    source_id:         Mapped[uuid.UUID | None]       = mapped_column(UUID(as_uuid=True))
    created_by:        Mapped[uuid.UUID | None]       = _user_fk()
    updated_by:        Mapped[uuid.UUID | None]       = _user_fk()
    created_at:        Mapped[datetime.datetime]      = _created_at()
    updated_at:        Mapped[datetime.datetime]      = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                                      server_default=text("now()"), onupdate=datetime.datetime.utcnow)
    deleted_at:        Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    deleted_by:        Mapped[uuid.UUID | None]       = _user_fk()


class NetPort(Base):
    __tablename__ = "net_ports"

    id:             Mapped[uuid.UUID]         = _uuid_pk()
    tenant_id:      Mapped[uuid.UUID]         = _tenant()
    asset_id:       Mapped[uuid.UUID]         = mapped_column(UUID(as_uuid=True), ForeignKey("net_assets.id", ondelete="CASCADE"), nullable=False)
    port_label:     Mapped[str]               = mapped_column(String(30), nullable=False)
    port_no:        Mapped[int | None]        = mapped_column(Integer)
    port_type:      Mapped[str]               = mapped_column(String(20), nullable=False)
    direction:      Mapped[str]               = mapped_column(String(4), nullable=False, default="BIDI")
    total_capacity: Mapped[int | None]        = mapped_column(Integer)
    used_capacity:  Mapped[int | None]        = mapped_column(Integer)
    status:         Mapped[str]               = mapped_column(String(20), nullable=False, default="FREE")
    attributes:     Mapped[dict[str, Any]]    = mapped_column(JSONB, nullable=False, default=dict)
    source_table:   Mapped[str | None]        = mapped_column(String(50))
    source_id:      Mapped[uuid.UUID | None]  = mapped_column(UUID(as_uuid=True))
    created_at:     Mapped[datetime.datetime] = _created_at()
    updated_at:     Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                              server_default=text("now()"), onupdate=datetime.datetime.utcnow)


class NetConnection(Base):
    """Explicit topology (Phase 3): source feeds dest, source nearer the OLT.

    Rows with source_table set are DERIVED from other explicit data (a
    cable's endpoints, an upload's cabinet / parent-splitter / parent-FDT
    reference) and are kept in step by topology.sync_derived_connections;
    rows without it were made by hand.
    """
    __tablename__ = "net_connections"

    id:               Mapped[uuid.UUID]          = _uuid_pk()
    tenant_id:        Mapped[uuid.UUID]          = _tenant()
    source_asset_id:  Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("net_assets.id", ondelete="CASCADE"), nullable=False)
    dest_asset_id:    Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("net_assets.id", ondelete="CASCADE"), nullable=False)
    source_port_id:   Mapped[uuid.UUID | None]   = mapped_column(UUID(as_uuid=True), ForeignKey("net_ports.id", ondelete="SET NULL"))
    dest_port_id:     Mapped[uuid.UUID | None]   = mapped_column(UUID(as_uuid=True), ForeignKey("net_ports.id", ondelete="SET NULL"))
    via_cable_id:     Mapped[uuid.UUID | None]   = mapped_column(UUID(as_uuid=True), ForeignKey("net_cables.id", ondelete="SET NULL"))
    fiber_id:         Mapped[uuid.UUID | None]   = mapped_column(UUID(as_uuid=True), ForeignKey("net_fibers.id", ondelete="SET NULL"))
    connection_type:  Mapped[str]                = mapped_column(String(20), nullable=False, default="FEED")
    lifecycle_status: Mapped[str]                = mapped_column(String(20), nullable=False, default="ACTIVE")
    design_id:        Mapped[uuid.UUID | None]   = mapped_column(UUID(as_uuid=True))
    attributes:       Mapped[dict[str, Any]]     = mapped_column(JSONB, nullable=False, default=dict)
    source_table:     Mapped[str | None]         = mapped_column(String(50))
    source_id:        Mapped[uuid.UUID | None]   = mapped_column(UUID(as_uuid=True))
    created_by:       Mapped[uuid.UUID | None]   = _user_fk()
    created_at:       Mapped[datetime.datetime]  = _created_at()
    updated_at:       Mapped[datetime.datetime]  = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                                server_default=text("now()"), onupdate=datetime.datetime.utcnow)
    deleted_at:       Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    deleted_by:       Mapped[uuid.UUID | None]   = _user_fk()


class NetFiber(Base):
    """A fibre in a cable. Stored only once something about it is recorded
    (status, assignment); unrecorded fibres are listed virtually from the
    cable's fiber_count (topology.fibres_for)."""
    __tablename__ = "net_fibers"

    id:          Mapped[uuid.UUID]          = _uuid_pk()
    tenant_id:   Mapped[uuid.UUID]          = _tenant()
    cable_id:    Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("net_cables.id", ondelete="CASCADE"), nullable=False)
    fiber_no:    Mapped[int]                = mapped_column(Integer, nullable=False)
    status:      Mapped[str]                = mapped_column(String(20), nullable=False, default="FREE")
    attributes:  Mapped[dict[str, Any]]     = mapped_column(JSONB, nullable=False, default=dict)
    created_at:  Mapped[datetime.datetime]  = _created_at()
    updated_at:  Mapped[datetime.datetime]  = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                           server_default=text("now()"), onupdate=datetime.datetime.utcnow)
