# ============================================================
# OPSYN DESIGN SCHEMAS — app/modules/design/schemas.py
# Wire contract for /projects/{id}/designs and /designs/*. Mirrored in
# frontend/shared-types/index.ts (Design, DesignSummary, …).
# ============================================================

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.modules.design.models import EDITABLE_STATUSES


class DesignCreate(BaseModel):
    name:          str = Field(min_length=1, max_length=200)
    description:   Optional[str] = None
    engine_config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("a design needs a name")
        return v


class BoundaryGeometry(BaseModel):
    type:        Literal["Polygon", "MultiPolygon"]
    coordinates: list[Any]


class DesignUpdate(BaseModel):
    name:          Optional[str] = Field(default=None, min_length=1, max_length=200)
    description:   Optional[str] = None
    status:        Optional[str] = None
    # null clears the boundary
    boundary:      Optional[BoundaryGeometry] = None
    engine_config: Optional[dict[str, Any]] = None

    @field_validator("status")
    @classmethod
    def _editable(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in EDITABLE_STATUSES:
            raise ValueError(f"status can only be set to {', '.join(EDITABLE_STATUSES)} here; "
                             "review, approval and deployment have their own steps")
        return v


class VersionRef(BaseModel):
    id:              str
    version_no:      int
    label:           Optional[str] = None
    creation_method: str
    created_at:      str


class DesignOut(BaseModel):
    id:              str
    project_id:      str
    project_name:    Optional[str] = None
    name:            str
    description:     Optional[str] = None
    status:          str
    boundary:        Optional[dict[str, Any]] = None
    # [minLng, minLat, maxLng, maxLat] of boundary, inputs and working set
    bbox:            Optional[list[float]] = None
    engine_config:   dict[str, Any]
    current_version: Optional[VersionRef] = None
    input_counts:    dict[str, int]
    created_at:      str
    updated_at:      str


class RouteEnd(BaseModel):
    asset_id: Optional[str] = None
    lng:      Optional[float] = None
    lat:      Optional[float] = None


class RouteRequest(BaseModel):
    start: RouteEnd = Field(alias="from")
    end:   RouteEnd = Field(alias="to")

    model_config = {"populate_by_name": True}


class GenerateRequest(BaseModel):
    """POST /designs/{id}/generate. engine_config: settings to use (and keep);
    replace: confirms replacing a non-empty working set (the old state is
    kept as its own version)."""
    engine_config: Optional[dict[str, Any]] = None
    replace: bool = False


class ImportRunRequest(BaseModel):
    run_id: str
    replace: bool = False


class SnapRequest(BaseModel):
    lng: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    radius_m: float = Field(15.0, gt=0, le=200)
    targets: Optional[list[str]] = None


class SaveVersionRequest(BaseModel):
    label: str = Field(min_length=1, max_length=200)
