# ============================================================
# OPSYN NETWORK ROUTER — app/modules/network/router.py
#
#   GET    /network/assets                 paged list (type/status/bbox filters)
#   POST   /network/assets                 create a live asset       network.edit
#   GET    /network/assets/{id}            full detail for the inspector
#   PATCH  /network/assets/{id}            change fields / lifecycle network.edit
#   DELETE /network/assets/{id}            soft delete               network.edit
#   GET    /network/search                 code/name search, live assets only
#   POST   /network/assets/sync-uploaded   re-mirror uploaded OLT/cabinet/
#                                          splitter rows (the upload commit
#                                          also does this since Phase 2)
#   GET    /network/catalogue              types, code prefixes, attribute specs
#   GET    /network/codes/next             preview the next generated code
#   GET    /network/cables                 paged list (category/status/q)
#   POST   /network/cables                 create (as-built or hand-drawn)  network.edit
#   GET    /network/cables/{id}            full detail for the inspector
#   PATCH  /network/cables/{id}            change fields / lifecycle / line network.edit
#   DELETE /network/cables/{id}            soft delete                      network.edit
#   GET    /network/assets/{id}/connections  fed from / feeds (Phase 3)
#   GET    /network/assets/{id}/trace        ?direction=upstream|downstream
#   GET    /network/assets/{id}/utilisation  capacity, used, basis
#   POST   /network/connections            link two assets by hand          network.edit
#   DELETE /network/connections/{id}       remove a hand-made link          network.edit
#   GET    /network/cables/{id}/fibers     TIA-598 fibre list
#   PATCH  /network/cables/{id}/fibers/{n} record a fibre status            network.edit
#
# Responses use the standard {success, data} envelope (the frontend reads
# r.data.data). Errors: 404 unknown/other-tenant id, 409 duplicate code or
# illegal lifecycle move, 422 bad input.
# ============================================================

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException

from app.core.database import get_db
from app.dependencies.permissions import check_permission
from app.modules.design.audit import audited
from app.modules.network import cable_service, service, topology_service
from app.modules.network.asset_types import ASSET_TYPES, CABLE_CATEGORIES
from app.modules.network.backfill import run_backfill
from app.modules.network.catalogue import build_catalogue
from app.modules.network.codes import next_codes
from app.modules.network.schemas import (
    AssetCreate, AssetUpdate, BackfillOut, CableCreate, CableUpdate, ConnectionCreate, FibreUpdate,
)
from app.modules.staff.models import User

router = APIRouter()


def _csv(value: Optional[str]) -> list[str] | None:
    if not value:
        return None
    return [v.strip().upper() for v in value.split(",") if v.strip()]


@router.get("/network/assets")
async def list_assets(
    type:   Optional[str] = Query(None, description="Comma-separated asset types"),
    status_: Optional[str] = Query(None, alias="status", description="Comma-separated lifecycle states"),
    bbox:   Optional[str] = Query(None, description="minLng,minLat,maxLng,maxLat"),
    q:      Optional[str] = Query(None, max_length=100, description="Code or name contains"),
    page:   int           = Query(1, ge=1),
    size:   int           = Query(50, ge=1, le=service.MAX_PAGE_SIZE),
    db:     AsyncSession  = Depends(get_db),
    caller: User          = Depends(check_permission("network.view")),
):
    items, total = await service.list_assets(
        db, caller.tenant_id, types=_csv(type), statuses=_csv(status_),
        bbox=service.parse_bbox(bbox), page=page, size=size, q=q,
    )
    return {"success": True, "data": {
        "items": [i.model_dump() for i in items], "total": total, "page": page, "size": size,
        "total_pages": max(1, -(-total // size)),
    }}


@router.get("/network/search")
async def search_assets(
    q:      str           = Query(..., min_length=1, max_length=100),
    field:  str           = Query("any", pattern="^(any|code|name)$"),
    type:   Optional[str] = Query(None),
    limit:  int           = Query(20, ge=1, le=service.MAX_SEARCH_RESULTS),
    db:     AsyncSession  = Depends(get_db),
    caller: User          = Depends(check_permission("network.view")),
):
    results = await service.search_assets(
        db, caller.tenant_id, q, field=field,
        asset_type=type.upper() if type else None, limit=limit,
    )
    return {"success": True, "data": [r.model_dump() for r in results]}


@router.post("/network/assets/sync-uploaded")
async def sync_uploaded_assets(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(audited("network.edit")),
):
    result = await run_backfill(db, caller.tenant_id)
    return {"success": True, "data": BackfillOut(mirrored=result.mirrored, skipped=result.skipped).model_dump()}


@router.post("/network/assets", status_code=status.HTTP_201_CREATED)
async def create_asset(
    body:   AssetCreate,
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(audited("network.edit")),
):
    asset = await service.create_asset(db, caller.tenant_id, caller, body)
    return {"success": True, "data": asset.model_dump()}


@router.get("/network/assets/{asset_id}")
async def get_asset(
    asset_id: str,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(check_permission("network.view")),
):
    asset = await service.get_asset(db, caller.tenant_id, asset_id)
    return {"success": True, "data": asset.model_dump()}


@router.patch("/network/assets/{asset_id}")
async def update_asset(
    asset_id: str,
    body:     AssetUpdate,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(audited("network.edit")),
):
    asset = await service.update_asset(db, caller.tenant_id, caller, asset_id, body)
    return {"success": True, "data": asset.model_dump()}


@router.delete("/network/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: str,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(audited("network.edit")),
):
    await service.delete_asset(db, caller.tenant_id, caller, asset_id)


# ── Catalogue & codes ────────────────────────────────────────

@router.get("/network/catalogue")
async def get_catalogue(caller: User = Depends(check_permission("network.view"))):
    return {"success": True, "data": build_catalogue()}


@router.get("/network/codes/next")
async def preview_next_code(
    kind:   str          = Query(..., pattern="^(asset|cable)$"),
    type:   str          = Query(..., description="Asset type or cable category"),
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("network.view")),
):
    key = type.upper()
    if key not in (ASSET_TYPES if kind == "asset" else CABLE_CATEGORIES):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown {kind} type '{type}'")
    # A preview only: another writer may take this code before it is used
    code = (await next_codes(db, caller.tenant_id, kind, key, lock=False))[0]
    return {"success": True, "data": {"code": code}}


# ── Cables ───────────────────────────────────────────────────

@router.get("/network/cables")
async def list_cables(
    category: Optional[str] = Query(None, description="Comma-separated cable categories"),
    status_:  Optional[str] = Query(None, alias="status"),
    q:        Optional[str] = Query(None, max_length=100),
    page:     int           = Query(1, ge=1),
    size:     int           = Query(50, ge=1, le=service.MAX_PAGE_SIZE),
    db:       AsyncSession  = Depends(get_db),
    caller:   User          = Depends(check_permission("network.view")),
):
    items, total = await cable_service.list_cables(
        db, caller.tenant_id, categories=_csv(category), statuses=_csv(status_), q=q, page=page, size=size,
    )
    return {"success": True, "data": {
        "items": [i.model_dump() for i in items], "total": total, "page": page, "size": size,
        "total_pages": max(1, -(-total // size)),
    }}


@router.post("/network/cables", status_code=status.HTTP_201_CREATED)
async def create_cable(
    body:   CableCreate,
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(audited("network.edit")),
):
    cable = await cable_service.create_cable(db, caller.tenant_id, caller, body)
    return {"success": True, "data": cable.model_dump()}


@router.get("/network/cables/{cable_id}")
async def get_cable(
    cable_id: str,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(check_permission("network.view")),
):
    cable = await cable_service.get_cable(db, caller.tenant_id, cable_id)
    return {"success": True, "data": cable.model_dump()}


@router.patch("/network/cables/{cable_id}")
async def update_cable(
    cable_id: str,
    body:     CableUpdate,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(audited("network.edit")),
):
    cable = await cable_service.update_cable(db, caller.tenant_id, caller, cable_id, body)
    return {"success": True, "data": cable.model_dump()}


@router.delete("/network/cables/{cable_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cable(
    cable_id: str,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(audited("network.edit")),
):
    await cable_service.delete_cable(db, caller.tenant_id, caller, cable_id)


# ── Topology (Phase 3) ───────────────────────────────────────

@router.get("/network/assets/{asset_id}/connections")
async def get_asset_connections(
    asset_id: str,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(check_permission("network.view")),
):
    result = await topology_service.list_connections(db, caller.tenant_id, asset_id)
    return {"success": True, "data": result.model_dump()}


@router.get("/network/assets/{asset_id}/trace")
async def trace_asset(
    asset_id:  str,
    direction: str          = Query("upstream", pattern="^(upstream|downstream)$"),
    db:        AsyncSession = Depends(get_db),
    caller:    User         = Depends(check_permission("network.view")),
):
    result = await topology_service.trace(db, caller.tenant_id, asset_id, direction)
    return {"success": True, "data": result.model_dump()}


@router.get("/network/assets/{asset_id}/utilisation")
async def asset_utilisation(
    asset_id: str,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(check_permission("network.view")),
):
    result = await topology_service.utilisation(db, caller.tenant_id, asset_id)
    return {"success": True, "data": result.model_dump()}


@router.post("/network/connections", status_code=status.HTTP_201_CREATED)
async def create_connection(
    body:   ConnectionCreate,
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(audited("network.edit")),
):
    result = await topology_service.create_connection(db, caller.tenant_id, caller, body)
    return {"success": True, "data": result.model_dump()}


@router.delete("/network/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: str,
    db:            AsyncSession = Depends(get_db),
    caller:        User         = Depends(audited("network.edit")),
):
    await topology_service.delete_connection(db, caller.tenant_id, caller, connection_id)


@router.get("/network/cables/{cable_id}/fibers")
async def list_cable_fibres(
    cable_id: str,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(check_permission("network.view")),
):
    fibres = await topology_service.list_fibres(db, caller.tenant_id, cable_id)
    return {"success": True, "data": [f.model_dump() for f in fibres]}


@router.patch("/network/cables/{cable_id}/fibers/{fiber_no}")
async def update_cable_fibre(
    cable_id: str,
    fiber_no: int,
    body:     FibreUpdate,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(audited("network.edit")),
):
    fibre = await topology_service.set_fibre_status(db, caller.tenant_id, caller, cable_id, fiber_no, body.status)
    return {"success": True, "data": fibre.model_dump()}
