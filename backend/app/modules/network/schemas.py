# ============================================================
# OPSYN NETWORK SCHEMAS — app/modules/network/schemas.py
#
# The wire contract for /network/*. Mirrored field-for-field in
# frontend/shared-types/index.ts (NetAsset, NetAssetSummary, …): change
# one, change the other. Geometry travels as GeoJSON in EPSG:4326,
# coordinates [longitude, latitude].
# ============================================================

from __future__ import annotations

import math
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.modules.network.asset_types import ASSET_TYPES
from app.modules.network.lifecycle import LIFECYCLE_STATES


class PointGeometry(BaseModel):
    type: Literal["Point"]
    coordinates: list[float] = Field(min_length=2, max_length=2)

    @field_validator("coordinates")
    @classmethod
    def _in_range(cls, v: list[float]) -> list[float]:
        lng, lat = v
        if not (math.isfinite(lng) and math.isfinite(lat)):
            raise ValueError("coordinates must be finite numbers")
        if not -180 <= lng <= 180:
            raise ValueError("longitude must be between -180 and 180")
        if not -90 <= lat <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if lng == 0 and lat == 0:
            raise ValueError("(0, 0) is not a real location — the coordinates are missing")
        return v


def _check_asset_type(v: str) -> str:
    if v not in ASSET_TYPES:
        raise ValueError(f"unknown asset type '{v}'")
    return v


def _check_lifecycle(v: Optional[str]) -> Optional[str]:
    if v is not None and v not in LIFECYCLE_STATES:
        raise ValueError(f"unknown lifecycle status '{v}'")
    return v


class AssetCreate(BaseModel):
    # Omitted or blank → generated (FAT-0015); see codes.py
    asset_code:       Optional[str] = Field(default=None, max_length=100)
    asset_type:       str
    name:             Optional[str] = Field(default=None, max_length=200)
    description:      Optional[str] = None
    geometry:         PointGeometry
    lifecycle_status: Optional[str] = None
    attributes:       dict[str, Any] = Field(default_factory=dict)
    capacity:         Optional[int] = Field(default=None, ge=0)
    used_capacity:    Optional[int] = Field(default=None, ge=0)
    parent_id:        Optional[str] = None
    project_id:       Optional[str] = None

    @field_validator("asset_type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        return _check_asset_type(v)

    @field_validator("lifecycle_status")
    @classmethod
    def _valid_lifecycle(cls, v: Optional[str]) -> Optional[str]:
        return _check_lifecycle(v)

    @field_validator("asset_code")
    @classmethod
    def _strip_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return v.strip() or None


class AssetUpdate(BaseModel):
    """Every field optional; only the fields sent are changed."""
    asset_code:       Optional[str] = Field(default=None, min_length=1, max_length=100)
    name:             Optional[str] = Field(default=None, max_length=200)
    description:      Optional[str] = None
    geometry:         Optional[PointGeometry] = None
    lifecycle_status: Optional[str] = None
    attributes:       Optional[dict[str, Any]] = None
    capacity:         Optional[int] = Field(default=None, ge=0)
    used_capacity:    Optional[int] = Field(default=None, ge=0)
    parent_id:        Optional[str] = None
    project_id:       Optional[str] = None

    @field_validator("lifecycle_status")
    @classmethod
    def _valid_lifecycle(cls, v: Optional[str]) -> Optional[str]:
        return _check_lifecycle(v)

    @field_validator("asset_code")
    @classmethod
    def _strip_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("asset code cannot be blank")
        return v


class AssetRef(BaseModel):
    id:         str
    asset_code: str
    asset_type: str
    name:       Optional[str] = None


class AssetSummary(BaseModel):
    """List/search row: enough to label, place and select an asset."""
    id:               str
    asset_code:       str
    asset_type:       str
    name:             Optional[str] = None
    lifecycle_status: str
    lng:              float
    lat:              float


class AssetOut(BaseModel):
    id:               str
    asset_code:       str
    asset_type:       str
    name:             Optional[str] = None
    description:      Optional[str] = None
    lifecycle_status: str
    creation_method:  str
    geometry:         dict[str, Any]
    lng:              float
    lat:              float
    attributes:       dict[str, Any]
    capacity:         Optional[int] = None
    used_capacity:    Optional[int] = None
    parent:           Optional[AssetRef] = None
    children_count:   int = 0
    project_id:       Optional[str] = None
    design_id:        Optional[str] = None
    lineage_id:       str
    source_table:     Optional[str] = None
    allowed_transitions: list[str]
    created_at:       str
    updated_at:       str


class BackfillOut(BaseModel):
    mirrored: dict[str, int]
    skipped:  list[dict[str, str]]


# ── Cables ───────────────────────────────────────────────────

class LineGeometry(BaseModel):
    type: Literal["LineString"]
    coordinates: list[list[float]] = Field(min_length=2, max_length=5000)

    @field_validator("coordinates")
    @classmethod
    def _points(cls, v: list[list[float]]) -> list[list[float]]:
        for pt in v:
            if len(pt) < 2:
                raise ValueError("every vertex needs a longitude and a latitude")
            PointGeometry(type="Point", coordinates=pt[:2])  # same range checks
        if all(p[:2] == v[0][:2] for p in v):
            raise ValueError("a cable needs at least two distinct vertices")
        return [p[:2] for p in v]


def _check_category(v: str) -> str:
    from app.modules.network.asset_types import CABLE_CATEGORIES
    if v not in CABLE_CATEGORIES:
        raise ValueError(f"unknown cable category '{v}'")
    return v


class CableCreate(BaseModel):
    asset_code:        Optional[str] = Field(default=None, max_length=100)
    cable_category:    str
    name:              Optional[str] = Field(default=None, max_length=200)
    description:       Optional[str] = None
    geometry:          LineGeometry
    # ROAD_GRAPH cables come from the routing service (design phases), never
    # from a client-supplied line; a line drawn here is either as-built
    # (IMPORTED) or hand-drawn (MANUAL_GEOMETRY, flagged by validation).
    route_method:      Literal["MANUAL_GEOMETRY", "IMPORTED"] = "MANUAL_GEOMETRY"
    fiber_count:       Optional[int] = Field(default=None, gt=0)
    installation_type: Optional[str] = None
    lifecycle_status:  Optional[str] = None
    source_asset_id:   Optional[str] = None
    dest_asset_id:     Optional[str] = None
    attributes:        dict[str, Any] = Field(default_factory=dict)

    @field_validator("cable_category")
    @classmethod
    def _valid_category(cls, v: str) -> str:
        return _check_category(v)

    @field_validator("lifecycle_status")
    @classmethod
    def _valid_lifecycle(cls, v: Optional[str]) -> Optional[str]:
        return _check_lifecycle(v)

    @field_validator("installation_type")
    @classmethod
    def _valid_installation(cls, v: Optional[str]) -> Optional[str]:
        from app.modules.network.asset_types import INSTALLATION_TYPES
        if v is not None and v not in INSTALLATION_TYPES:
            raise ValueError(f"unknown installation type '{v}'")
        return v

    @field_validator("asset_code")
    @classmethod
    def _strip_code(cls, v: Optional[str]) -> Optional[str]:
        return (v.strip() or None) if v is not None else None


class CableUpdate(BaseModel):
    asset_code:        Optional[str] = Field(default=None, min_length=1, max_length=100)
    name:              Optional[str] = Field(default=None, max_length=200)
    description:       Optional[str] = None
    geometry:          Optional[LineGeometry] = None
    fiber_count:       Optional[int] = Field(default=None, gt=0)
    installation_type: Optional[str] = None
    lifecycle_status:  Optional[str] = None
    source_asset_id:   Optional[str] = None
    dest_asset_id:     Optional[str] = None
    attributes:        Optional[dict[str, Any]] = None

    @field_validator("lifecycle_status")
    @classmethod
    def _valid_lifecycle(cls, v: Optional[str]) -> Optional[str]:
        return _check_lifecycle(v)

    @field_validator("installation_type")
    @classmethod
    def _valid_installation(cls, v: Optional[str]) -> Optional[str]:
        from app.modules.network.asset_types import INSTALLATION_TYPES
        if v is not None and v not in INSTALLATION_TYPES:
            raise ValueError(f"unknown installation type '{v}'")
        return v


class CableSummary(BaseModel):
    id:               str
    asset_code:       str
    cable_category:   str
    name:             Optional[str] = None
    lifecycle_status: str
    length_m:         Optional[float] = None
    fiber_count:      Optional[int] = None


class CableOut(BaseModel):
    id:                  str
    asset_code:          str
    cable_category:      str
    name:                Optional[str] = None
    description:         Optional[str] = None
    lifecycle_status:    str
    creation_method:     str
    route_method:        str
    installation_type:   Optional[str] = None
    fiber_count:         Optional[int] = None
    length_m:            Optional[float] = None
    geometry:            dict[str, Any]
    midpoint:            list[float]
    bbox:                list[float]
    source:              Optional[AssetRef] = None
    dest:                Optional[AssetRef] = None
    attributes:          dict[str, Any]
    project_id:          Optional[str] = None
    design_id:           Optional[str] = None
    lineage_id:          str
    source_table:        Optional[str] = None
    allowed_transitions: list[str]
    created_at:          str
    updated_at:          str


# ── Topology (Phase 3) ───────────────────────────────────────

class ConnectionCreate(BaseModel):
    """source feeds dest (source is nearer the OLT)."""
    source_asset_id: str
    dest_asset_id:   str
    connection_type: str = "FEED"
    via_cable_id:    Optional[str] = None

    @field_validator("connection_type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        from app.modules.network.asset_types import CONNECTION_TYPES
        if v not in CONNECTION_TYPES:
            raise ValueError(f"connection_type must be one of {', '.join(CONNECTION_TYPES)}")
        return v


class CableRef(BaseModel):
    id:             str
    asset_code:     str
    cable_category: str
    length_m:       Optional[float] = None


class ConnectionOut(BaseModel):
    id:               str
    connection_type:  str
    lifecycle_status: str
    # Where a derived connection comes from (net_cables, attr:…); None = made by hand
    derived_from:     Optional[str] = None
    peer:             AssetRef
    via_cable:        Optional[CableRef] = None


class AssetConnections(BaseModel):
    upstream:   list[ConnectionOut]
    downstream: list[ConnectionOut]


class TraceAsset(BaseModel):
    id:               str
    asset_code:       str
    asset_type:       str
    name:             Optional[str] = None
    lifecycle_status: str
    lng:              float
    lat:              float


class TraceHop(BaseModel):
    asset:           TraceAsset
    depth:           int
    from_id:         Optional[str] = None
    connection_type: Optional[str] = None
    via_cable:       Optional[CableRef] = None


class TraceOut(BaseModel):
    direction:      Literal["upstream", "downstream"]
    start_id:       str
    hops:           list[TraceHop]
    # upstream: start → root along the first path found; downstream: empty
    path_ids:       list[str]
    root:           Optional[TraceAsset] = None
    reached_root:   bool
    path_length_m:  Optional[float] = None
    counts_by_type: dict[str, int]
    customers:      int
    truncated:      bool
    geometry:       dict[str, Any]


class UtilisationOut(BaseModel):
    capacity:       Optional[int] = None
    used:           Optional[int] = None
    available:      Optional[int] = None
    pct:            Optional[float] = None
    state:          str
    basis:          str
    capacity_label: Optional[str] = None


class FibreOut(BaseModel):
    fiber_no:        int
    tube_no:         int
    position:        int
    colour:          str
    colour_hex:      str
    tube_colour:     str
    tube_colour_hex: str
    status:          str
    recorded:        bool


class FibreUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        from app.modules.network.asset_types import FIBER_STATUSES
        if v not in FIBER_STATUSES:
            raise ValueError(f"status must be one of {', '.join(FIBER_STATUSES)}")
        return v
