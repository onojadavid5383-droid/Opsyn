# ============================================================
# OPSYN INFRASTRUCTURE ROUTER — app/modules/infrastructure/router.py
# FTTx network asset registry: sites, nodes, routes
# ============================================================

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Query, File, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.permissions import check_permission
from app.modules.staff.models import User
from app.modules.infrastructure.models import (
    InfrastructureSite, InfrastructureNode, InfrastructureRoute,
    InfraPort, InfraSubscriber, InfraCapacityAlert,
    InfraUploadSession, InfraDeletionSession, Cabinet, OLT, SplitterBox,
    InfraAuditLog,
)
from app.modules.infrastructure.upload_service import (
    run_full_validation, commit_session, generate_error_report_xlsx,
)
from app.modules.infrastructure.deletion_service import (
    validate_deletion_file,
    match_deletion_keys_splitter,
    match_deletion_keys_cabinet,
    match_deletion_keys_olt,
    collect_cascade_targets,
    execute_deletion,
)

router = APIRouter()


# ── Pydantic schemas ─────────────────────────────────────────

class SiteCreate(BaseModel):
    name:      str             = Field(..., max_length=200)
    site_type: str             = Field("POP", max_length=30)
    address:   Optional[str]   = None
    latitude:  Optional[float] = None
    longitude: Optional[float] = None
    region_id: Optional[uuid.UUID] = None
    status:    str             = Field("active", max_length=20)
    notes:     Optional[str]   = None


class SiteUpdate(BaseModel):
    name:      Optional[str]   = None
    site_type: Optional[str]   = None
    address:   Optional[str]   = None
    latitude:  Optional[float] = None
    longitude: Optional[float] = None
    region_id: Optional[uuid.UUID] = None
    status:    Optional[str]   = None
    notes:     Optional[str]   = None


class SiteOut(BaseModel):
    id:         uuid.UUID
    tenant_id:  uuid.UUID
    name:       str
    site_type:  str
    address:    Optional[str]   = None
    latitude:   Optional[float] = None
    longitude:  Optional[float] = None
    region_id:  Optional[uuid.UUID] = None
    status:     str
    notes:      Optional[str]   = None
    created_by: Optional[uuid.UUID] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_obj(cls, obj: InfrastructureSite) -> "SiteOut":
        return cls(
            id=obj.id, tenant_id=obj.tenant_id, name=obj.name,
            site_type=obj.site_type, address=obj.address,
            latitude=float(obj.latitude) if obj.latitude is not None else None,
            longitude=float(obj.longitude) if obj.longitude is not None else None,
            region_id=obj.region_id, status=obj.status, notes=obj.notes,
            created_by=obj.created_by,
            created_at=obj.created_at.isoformat(),
            updated_at=obj.updated_at.isoformat(),
        )


class NodeCreate(BaseModel):
    name:         str              = Field(..., max_length=200)
    node_type:    str              = Field("OLT", max_length=30)
    site_id:      Optional[uuid.UUID] = None
    manufacturer: Optional[str]   = None
    model:        Optional[str]   = None
    ip_address:   Optional[str]   = Field(None, max_length=45)
    port_count:   Optional[int]   = None
    status:       str              = Field("active", max_length=20)
    meta:         Optional[dict]  = None


class NodeUpdate(BaseModel):
    name:         Optional[str]   = None
    node_type:    Optional[str]   = None
    site_id:      Optional[uuid.UUID] = None
    manufacturer: Optional[str]   = None
    model:        Optional[str]   = None
    ip_address:   Optional[str]   = None
    port_count:   Optional[int]   = None
    status:       Optional[str]   = None
    meta:         Optional[dict]  = None


class NodeOut(BaseModel):
    id:           uuid.UUID
    tenant_id:    uuid.UUID
    site_id:      Optional[uuid.UUID] = None
    name:         str
    node_type:    str
    manufacturer: Optional[str] = None
    model:        Optional[str] = None
    ip_address:   Optional[str] = None
    port_count:   Optional[int] = None
    status:       str
    meta:         Optional[dict] = None
    created_by:   Optional[uuid.UUID] = None
    created_at:   str
    updated_at:   str

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_obj(cls, obj: InfrastructureNode) -> "NodeOut":
        return cls(
            id=obj.id, tenant_id=obj.tenant_id, site_id=obj.site_id,
            name=obj.name, node_type=obj.node_type,
            manufacturer=obj.manufacturer, model=obj.model,
            ip_address=obj.ip_address, port_count=obj.port_count,
            status=obj.status, meta=obj.meta, created_by=obj.created_by,
            created_at=obj.created_at.isoformat(),
            updated_at=obj.updated_at.isoformat(),
        )


class RouteCreate(BaseModel):
    from_node_id:  uuid.UUID
    to_node_id:    uuid.UUID
    cable_type:    Optional[str]   = None
    length_km:     Optional[float] = None
    capacity_gbps: Optional[float] = None
    status:        str             = Field("active", max_length=20)
    installed_at:  Optional[date]  = None
    notes:         Optional[str]   = None


class RouteUpdate(BaseModel):
    cable_type:    Optional[str]   = None
    length_km:     Optional[float] = None
    capacity_gbps: Optional[float] = None
    status:        Optional[str]   = None
    installed_at:  Optional[date]  = None
    notes:         Optional[str]   = None


class RouteOut(BaseModel):
    id:            uuid.UUID
    tenant_id:     uuid.UUID
    from_node_id:  uuid.UUID
    to_node_id:    uuid.UUID
    cable_type:    Optional[str]   = None
    length_km:     Optional[float] = None
    capacity_gbps: Optional[float] = None
    status:        str
    installed_at:  Optional[str]   = None
    notes:         Optional[str]   = None
    created_by:    Optional[uuid.UUID] = None
    created_at:    str

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_obj(cls, obj: InfrastructureRoute) -> "RouteOut":
        return cls(
            id=obj.id, tenant_id=obj.tenant_id,
            from_node_id=obj.from_node_id, to_node_id=obj.to_node_id,
            cable_type=obj.cable_type,
            length_km=float(obj.length_km) if obj.length_km is not None else None,
            capacity_gbps=float(obj.capacity_gbps) if obj.capacity_gbps is not None else None,
            status=obj.status,
            installed_at=obj.installed_at.isoformat() if obj.installed_at else None,
            notes=obj.notes, created_by=obj.created_by,
            created_at=obj.created_at.isoformat(),
        )


# ── Sites ────────────────────────────────────────────────────

@router.get("/infrastructure/sites", response_model=dict)
async def list_sites(
    page:   int = Query(1, ge=1),
    size:   int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("infrastructure.view")),
):
    q = select(InfrastructureSite).where(
        InfrastructureSite.tenant_id == caller.tenant_id
    )
    if status:
        q = q.where(InfrastructureSite.status == status)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows  = (await db.execute(q.order_by(InfrastructureSite.name).offset((page - 1) * size).limit(size))).scalars().all()
    return {
        "total": total, "page": page, "size": size,
        "items": [SiteOut.from_orm_obj(r) for r in rows],
    }


@router.post("/infrastructure/sites", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
async def create_site(
    payload: SiteCreate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.edit")),
):
    site = InfrastructureSite(
        tenant_id=caller.tenant_id,
        created_by=caller.id,
        **payload.model_dump(),
    )
    db.add(site)
    await db.commit()
    await db.refresh(site)
    return SiteOut.from_orm_obj(site)


@router.get("/infrastructure/sites/{site_id}", response_model=SiteOut)
async def get_site(
    site_id: uuid.UUID,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.view")),
):
    site = await db.get(InfrastructureSite, site_id)
    if not site or site.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Site not found")
    return SiteOut.from_orm_obj(site)


@router.put("/infrastructure/sites/{site_id}", response_model=SiteOut)
async def update_site(
    site_id: uuid.UUID,
    payload: SiteUpdate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.edit")),
):
    site = await db.get(InfrastructureSite, site_id)
    if not site or site.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Site not found")

    for field, val in payload.model_dump(exclude_unset=True).items():
        setattr(site, field, val)
    await db.commit()
    await db.refresh(site)
    return SiteOut.from_orm_obj(site)


@router.delete("/infrastructure/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(
    site_id: uuid.UUID,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.edit")),
):
    site = await db.get(InfrastructureSite, site_id)
    if not site or site.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Site not found")
    await db.delete(site)
    await db.commit()


# ── Nodes ────────────────────────────────────────────────────

@router.get("/infrastructure/nodes", response_model=dict)
async def list_nodes(
    page:    int = Query(1, ge=1),
    size:    int = Query(50, ge=1, le=200),
    site_id: Optional[uuid.UUID] = Query(None),
    status:  Optional[str]       = Query(None),
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.view")),
):
    q = select(InfrastructureNode).where(
        InfrastructureNode.tenant_id == caller.tenant_id
    )
    if site_id:
        q = q.where(InfrastructureNode.site_id == site_id)
    if status:
        q = q.where(InfrastructureNode.status == status)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows  = (await db.execute(q.order_by(InfrastructureNode.name).offset((page - 1) * size).limit(size))).scalars().all()
    return {
        "total": total, "page": page, "size": size,
        "items": [NodeOut.from_orm_obj(r) for r in rows],
    }


@router.post("/infrastructure/nodes", response_model=NodeOut, status_code=status.HTTP_201_CREATED)
async def create_node(
    payload: NodeCreate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.edit")),
):
    node = InfrastructureNode(
        tenant_id=caller.tenant_id,
        created_by=caller.id,
        **payload.model_dump(),
    )
    db.add(node)
    await db.commit()
    await db.refresh(node)
    return NodeOut.from_orm_obj(node)


@router.get("/infrastructure/nodes/{node_id}", response_model=NodeOut)
async def get_node(
    node_id: uuid.UUID,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.view")),
):
    node = await db.get(InfrastructureNode, node_id)
    if not node or node.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Node not found")
    return NodeOut.from_orm_obj(node)


@router.put("/infrastructure/nodes/{node_id}", response_model=NodeOut)
async def update_node(
    node_id: uuid.UUID,
    payload: NodeUpdate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.edit")),
):
    node = await db.get(InfrastructureNode, node_id)
    if not node or node.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Node not found")

    for field, val in payload.model_dump(exclude_unset=True).items():
        setattr(node, field, val)
    await db.commit()
    await db.refresh(node)
    return NodeOut.from_orm_obj(node)


@router.delete("/infrastructure/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    node_id: uuid.UUID,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.edit")),
):
    node = await db.get(InfrastructureNode, node_id)
    if not node or node.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Node not found")
    await db.delete(node)
    await db.commit()


# ── Routes ───────────────────────────────────────────────────

@router.get("/infrastructure/routes", response_model=dict)
async def list_routes(
    page:         int = Query(1, ge=1),
    size:         int = Query(50, ge=1, le=200),
    from_node_id: Optional[uuid.UUID] = Query(None),
    to_node_id:   Optional[uuid.UUID] = Query(None),
    status:       Optional[str]       = Query(None),
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("infrastructure.view")),
):
    q = select(InfrastructureRoute).where(
        InfrastructureRoute.tenant_id == caller.tenant_id
    )
    if from_node_id:
        q = q.where(InfrastructureRoute.from_node_id == from_node_id)
    if to_node_id:
        q = q.where(InfrastructureRoute.to_node_id == to_node_id)
    if status:
        q = q.where(InfrastructureRoute.status == status)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows  = (await db.execute(q.order_by(InfrastructureRoute.created_at.desc()).offset((page - 1) * size).limit(size))).scalars().all()
    return {
        "total": total, "page": page, "size": size,
        "items": [RouteOut.from_orm_obj(r) for r in rows],
    }


@router.post("/infrastructure/routes", response_model=RouteOut, status_code=status.HTTP_201_CREATED)
async def create_route(
    payload: RouteCreate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.edit")),
):
    route = InfrastructureRoute(
        tenant_id=caller.tenant_id,
        created_by=caller.id,
        **payload.model_dump(),
    )
    db.add(route)
    await db.commit()
    await db.refresh(route)
    return RouteOut.from_orm_obj(route)


@router.get("/infrastructure/routes/{route_id}", response_model=RouteOut)
async def get_route(
    route_id: uuid.UUID,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(check_permission("infrastructure.view")),
):
    route = await db.get(InfrastructureRoute, route_id)
    if not route or route.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Route not found")
    return RouteOut.from_orm_obj(route)


@router.delete("/infrastructure/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(
    route_id: uuid.UUID,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(check_permission("infrastructure.edit")),
):
    route = await db.get(InfrastructureRoute, route_id)
    if not route or route.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Route not found")
    await db.delete(route)
    await db.commit()


# ── Network summary (for map view) ───────────────────────────

@router.get("/infrastructure/summary")
async def infrastructure_summary(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("infrastructure.view")),
):
    from sqlalchemy import text
    result = await db.execute(
        text("""
            SELECT
                (SELECT COUNT(*) FROM infrastructure_sites  WHERE tenant_id = :tid AND status = 'active') AS active_sites,
                (SELECT COUNT(*) FROM infrastructure_nodes  WHERE tenant_id = :tid AND status = 'active') AS active_nodes,
                (SELECT COUNT(*) FROM infrastructure_routes WHERE tenant_id = :tid AND status = 'active') AS active_routes,
                (SELECT COALESCE(SUM(length_km), 0) FROM infrastructure_routes WHERE tenant_id = :tid AND status = 'active') AS total_km,
                (SELECT COUNT(*) FROM infrastructure_nodes  WHERE tenant_id = :tid AND node_type = 'OLT') AS olt_count,
                (SELECT COUNT(*) FROM infrastructure_nodes  WHERE tenant_id = :tid AND node_type = 'AGG') AS agg_count
        """),
        {"tid": str(caller.tenant_id)},
    )
    row = result.fetchone()
    return {
        "active_sites":  row[0],
        "active_nodes":  row[1],
        "active_routes": row[2],
        "total_fiber_km": float(row[3]),
        "olt_count":     row[4],
        "agg_count":     row[5],
    }


# ── Map data endpoint (S4.2 Leaflet feed) ────────────────────

@router.get("/infrastructure/dashboard-map")
async def infrastructure_dashboard_map(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("infrastructure.view")),
):
    """Small map payload for the dashboard; excludes routes and unused assets."""
    sites_rows = (await db.execute(
        select(
            InfrastructureSite.id, InfrastructureSite.name, InfrastructureSite.site_type,
            InfrastructureSite.latitude, InfrastructureSite.longitude,
            InfrastructureSite.region_id, InfrastructureSite.status,
        ).where(InfrastructureSite.tenant_id == caller.tenant_id)
    )).all()

    olt_rows = (await db.execute(
        select(OLT.id, OLT.name, OLT.latitude, OLT.longitude).where(
            OLT.tenant_id == caller.tenant_id,
            OLT.is_deleted.is_(False),
        )
    )).all()

    alert_rows = (await db.execute(
        select(InfraCapacityAlert.site_id).where(
            InfraCapacityAlert.tenant_id == caller.tenant_id,
            InfraCapacityAlert.is_resolved.is_(False),
            InfraCapacityAlert.site_id.is_not(None),
        )
    )).all()
    alert_site_ids = {str(row[0]) for row in alert_rows}

    return {
        "sites": [
            {
                "id": str(row.id), "name": row.name, "site_type": row.site_type,
                "latitude": float(row.latitude) if row.latitude is not None else None,
                "longitude": float(row.longitude) if row.longitude is not None else None,
                "status": row.status,
                "region_id": str(row.region_id) if row.region_id else None,
                "is_monitored": False,
                "has_alert": str(row.id) in alert_site_ids,
            }
            for row in sites_rows
        ],
        "olts": [
            {"id": str(row.id), "name": row.name,
             "latitude": row.latitude, "longitude": row.longitude}
            for row in olt_rows
        ],
    }


@router.get("/infrastructure/map")
async def infrastructure_map(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("infrastructure.view")),
):
    """Returns all sites + nodes + routes in a single payload for the Leaflet map."""
    from sqlalchemy import text

    sites_rows = (await db.execute(
        select(InfrastructureSite).where(InfrastructureSite.tenant_id == caller.tenant_id)
    )).scalars().all()

    nodes_rows = (await db.execute(
        select(InfrastructureNode).where(InfrastructureNode.tenant_id == caller.tenant_id)
    )).scalars().all()

    routes_rows = (await db.execute(
        select(InfrastructureRoute).where(InfrastructureRoute.tenant_id == caller.tenant_id)
    )).scalars().all()

    # Per-node utilisation from infra_ports
    util_result = await db.execute(
        text("""
            SELECT node_id,
                   COALESCE(SUM(used_capacity), 0)  AS used,
                   COALESCE(SUM(total_capacity), 1) AS total
            FROM infra_ports
            WHERE tenant_id = :tid
            GROUP BY node_id
        """),
        {"tid": str(caller.tenant_id)},
    )
    util_map: dict[str, dict] = {
        str(r[0]): {"used": int(r[1]), "total": int(r[2]),
                    "pct": round(int(r[1]) / max(int(r[2]), 1) * 100)}
        for r in util_result.fetchall()
    }

    # Active unresolved capacity alerts
    alert_rows = (await db.execute(
        select(InfraCapacityAlert).where(
            InfraCapacityAlert.tenant_id == caller.tenant_id,
            InfraCapacityAlert.is_resolved.is_(False),
        )
    )).scalars().all()
    alert_node_ids = {str(a.node_id) for a in alert_rows if a.node_id}
    alert_site_ids = {str(a.site_id) for a in alert_rows if a.site_id}

    # Uploaded FTTH assets — Cabinets, OLTs, Splitter Boxes
    cabinets_rows = (await db.execute(
        select(Cabinet).where(
            Cabinet.tenant_id == caller.tenant_id,
            Cabinet.is_deleted.is_(False),
        )
    )).scalars().all()

    olts_rows = (await db.execute(
        select(OLT).where(
            OLT.tenant_id == caller.tenant_id,
            OLT.is_deleted.is_(False),
        )
    )).scalars().all()

    splitters_rows = (await db.execute(
        select(SplitterBox).where(
            SplitterBox.tenant_id == caller.tenant_id,
            SplitterBox.is_deleted.is_(False),
        )
    )).scalars().all()

    return {
        "sites": [
            {
                "id": str(s.id), "name": s.name, "site_type": s.site_type,
                "latitude": float(s.latitude) if s.latitude else None,
                "longitude": float(s.longitude) if s.longitude else None,
                "status": s.status, "region_id": str(s.region_id) if s.region_id else None,
                "is_monitored": getattr(s, "is_monitored", False),
                "has_alert": str(s.id) in alert_site_ids,
            }
            for s in sites_rows
        ],
        "nodes": [
            {
                "id": str(n.id), "name": n.name, "node_type": n.node_type,
                "site_id": str(n.site_id) if n.site_id else None,
                "ip_address": n.ip_address, "status": n.status,
                "utilisation": util_map.get(str(n.id), {"used": 0, "total": 0, "pct": 0}),
                "has_alert": str(n.id) in alert_node_ids,
            }
            for n in nodes_rows
        ],
        "routes": [
            {
                "id": str(r.id),
                "from_node_id": str(r.from_node_id), "to_node_id": str(r.to_node_id),
                "cable_type": r.cable_type, "status": r.status,
                "length_km": float(r.length_km) if r.length_km else None,
                "capacity_gbps": float(r.capacity_gbps) if r.capacity_gbps else None,
            }
            for r in routes_rows
        ],
        "cabinets": [
            {
                "id": str(c.id), "cabinet_id": c.cabinet_id,
                "latitude": c.latitude, "longitude": c.longitude,
                "capacity": c.capacity,
                "number_tray": c.number_tray,
            }
            for c in cabinets_rows
        ],
        "olts": [
            {
                "id": str(o.id), "name": o.name,
                "latitude": o.latitude, "longitude": o.longitude,
                "location_description": o.location_description,
                "number_of_odf": o.number_of_odf,
                "custom_data": o.custom_data or {},
            }
            for o in olts_rows
        ],
        "splitters": [
            {
                "id": str(s.id), "box_id": s.box_id,
                "latitude": s.latitude, "longitude": s.longitude,
                "splitter_level": s.splitter_level,
                "splitter_type": s.splitter_type,
                "input_ports": s.input_ports, "output_ports": s.output_ports,
                "number_customer": s.number_customer,
                # Topology for the map's path trace (splitter → parent → cabinet)
                "parent_splitter_id": str(s.parent_splitter_id) if s.parent_splitter_id else None,
                "cabinet_id": str(s.cabinet_id) if s.cabinet_id else None,
                "custom_data": s.custom_data or {},
            }
            for s in splitters_rows
        ],
    }


# ── Utilisation endpoint (heatmap layer) ─────────────────────

@router.get("/infrastructure/utilisation")
async def infrastructure_utilisation(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("infrastructure.view")),
):
    from sqlalchemy import text
    rows = (await db.execute(
        text("""
            SELECT s.id, s.name, s.latitude, s.longitude,
                   COALESCE(SUM(p.used_capacity), 0)  AS used,
                   COALESCE(SUM(p.total_capacity), 0) AS total
            FROM infrastructure_sites s
            JOIN infrastructure_nodes n ON n.site_id = s.id AND n.tenant_id = :tid
            LEFT JOIN infra_ports p     ON p.node_id  = n.id AND p.tenant_id = :tid
            WHERE s.tenant_id = :tid
            GROUP BY s.id, s.name, s.latitude, s.longitude
        """),
        {"tid": str(caller.tenant_id)},
    )).fetchall()
    return [
        {
            "site_id": str(r[0]), "name": r[1],
            "latitude": float(r[2]) if r[2] else None,
            "longitude": float(r[3]) if r[3] else None,
            "used": int(r[4]), "total": int(r[5]),
            "utilisation_pct": round(int(r[4]) / max(int(r[5]), 1) * 100),
        }
        for r in rows
    ]


# ── Ports ─────────────────────────────────────────────────────

class PortCreate(BaseModel):
    node_id:        uuid.UUID
    port_number:    str              = Field(..., max_length=20)
    port_type:      str              = Field("GPON", max_length=30)
    total_capacity: int              = 128
    used_capacity:  int              = 0
    status:         str              = Field("active", max_length=20)


class PortUpdate(BaseModel):
    port_type:      Optional[str] = None
    total_capacity: Optional[int] = None
    used_capacity:  Optional[int] = None
    status:         Optional[str] = None


@router.get("/infrastructure/nodes/{node_id}/ports")
async def list_ports(
    node_id: uuid.UUID,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.view")),
):
    rows = (await db.execute(
        select(InfraPort).where(
            InfraPort.tenant_id == caller.tenant_id,
            InfraPort.node_id == node_id,
        ).order_by(InfraPort.port_number)
    )).scalars().all()
    return [_port_dict(p) for p in rows]


@router.post("/infrastructure/nodes/{node_id}/ports", status_code=status.HTTP_201_CREATED)
async def create_port(
    node_id: uuid.UUID,
    payload: PortCreate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.edit")),
):
    port = InfraPort(
        tenant_id=caller.tenant_id,
        node_id=node_id,
        port_number=payload.port_number,
        port_type=payload.port_type,
        total_capacity=payload.total_capacity,
        used_capacity=payload.used_capacity,
        status=payload.status,
    )
    db.add(port)
    await db.commit()
    await db.refresh(port)
    return _port_dict(port)


@router.patch("/infrastructure/ports/{port_id}")
async def update_port(
    port_id: uuid.UUID,
    payload: PortUpdate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.edit")),
):
    port = await db.get(InfraPort, port_id)
    if not port or port.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Port not found")
    for field, val in payload.model_dump(exclude_unset=True).items():
        setattr(port, field, val)
    await db.commit()
    await db.refresh(port)
    return _port_dict(port)


@router.delete("/infrastructure/ports/{port_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_port(
    port_id: uuid.UUID,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.edit")),
):
    port = await db.get(InfraPort, port_id)
    if not port or port.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Port not found")
    await db.delete(port)
    await db.commit()


def _port_dict(p: InfraPort) -> dict:
    return {
        "id": str(p.id), "node_id": str(p.node_id),
        "port_number": p.port_number, "port_type": p.port_type,
        "total_capacity": p.total_capacity, "used_capacity": p.used_capacity,
        "utilisation_pct": round(p.used_capacity / max(p.total_capacity, 1) * 100),
        "status": p.status,
        "last_synced_at": p.last_synced_at.isoformat() if p.last_synced_at else None,
        "created_at": p.created_at.isoformat(),
    }


# ── Capacity alerts ───────────────────────────────────────────

@router.get("/infrastructure/capacity-alerts")
async def list_capacity_alerts(
    resolved: Optional[bool] = Query(None),
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(check_permission("infrastructure.view")),
):
    q = select(InfraCapacityAlert).where(InfraCapacityAlert.tenant_id == caller.tenant_id)
    if resolved is not None:
        q = q.where(InfraCapacityAlert.is_resolved == resolved)
    rows = (await db.execute(q.order_by(InfraCapacityAlert.created_at.desc()))).scalars().all()
    return [_alert_dict(a) for a in rows]


@router.patch("/infrastructure/capacity-alerts/{alert_id}/resolve", status_code=status.HTTP_200_OK)
async def resolve_capacity_alert(
    alert_id: uuid.UUID,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(check_permission("infrastructure.edit")),
):
    from datetime import datetime as _dt, timezone as _tz
    alert = await db.get(InfraCapacityAlert, alert_id)
    if not alert or alert.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.is_resolved = True
    alert.resolved_at = _dt.now(_tz.utc)
    await db.commit()
    await db.refresh(alert)
    return _alert_dict(alert)


def _alert_dict(a: InfraCapacityAlert) -> dict:
    return {
        "id": str(a.id), "site_id": str(a.site_id) if a.site_id else None,
        "node_id": str(a.node_id) if a.node_id else None,
        "alert_type": a.alert_type, "severity": a.severity,
        "threshold_pct": a.threshold_pct, "current_pct": a.current_pct,
        "message": a.message, "is_resolved": a.is_resolved,
        "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
        "linked_task_id": str(a.linked_task_id) if a.linked_task_id else None,
        "created_at": a.created_at.isoformat(),
    }


# ── Subscribers (Coverage Demand layer) ──────────────────────

@router.get("/infrastructure/subscribers")
async def list_subscribers(
    site_id:      Optional[uuid.UUID] = Query(None),
    node_id:      Optional[uuid.UUID] = Query(None),
    service_type: Optional[str]       = Query(None),
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("infrastructure.view")),
):
    q = select(InfraSubscriber).where(InfraSubscriber.tenant_id == caller.tenant_id)
    if site_id:
        q = q.where(InfraSubscriber.site_id == site_id)
    if node_id:
        q = q.where(InfraSubscriber.node_id == node_id)
    if service_type:
        q = q.where(InfraSubscriber.service_type == service_type)
    rows = (await db.execute(q.order_by(InfraSubscriber.created_at.desc()))).scalars().all()
    return [
        {
            "id": str(s.id), "customer_id": s.customer_id,
            "site_id": str(s.site_id) if s.site_id else None,
            "node_id": str(s.node_id) if s.node_id else None,
            "port_id": str(s.port_id) if s.port_id else None,
            "service_type": s.service_type, "status": s.status,
            "address": s.address,
            "latitude":  float(s.latitude)  if s.latitude  else None,
            "longitude": float(s.longitude) if s.longitude else None,
            "created_at": s.created_at.isoformat(),
        }
        for s in rows
    ]


# ── Manual sync trigger ───────────────────────────────────────

@router.post("/infrastructure/sync-ports", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync_ports(
    caller: User = Depends(check_permission("infrastructure.edit")),
):
    """Enqueue SmartOLT port sync immediately (returns 202 Accepted)."""
    from app.tasks.infrastructure_sync import sync_smartolt_ports
    sync_smartolt_ports.delay()
    return {"queued": True, "message": "Port sync task enqueued"}


# ═══════════════════════════════════════════════════════════════
# FTTH ASSET UPLOAD WORKFLOW  (Phase 3)
# POST  /infrastructure/upload/{asset_type}          — validate
# GET   /infrastructure/upload/{session_id}          — session status
# POST  /infrastructure/upload/{session_id}/commit   — commit to live tables
# GET   /infrastructure/upload/{session_id}/error-report — xlsx download
# ═══════════════════════════════════════════════════════════════

_LEGACY_UPLOAD_TYPES = {
    "olt":      ("OLTs", "Optical line terminals"),
    "cabinet":  ("Cabinets", "ODF splice cabinets"),
    "splitter": ("Splitter boxes", "First- and second-level GPON splitters"),
}


def _valid_upload_types() -> frozenset[str]:
    from app.modules.network.upload import NET_UPLOAD_TYPES
    return frozenset(_LEGACY_UPLOAD_TYPES) | frozenset(NET_UPLOAD_TYPES)


_VALID_UPLOAD_TYPES = _valid_upload_types()


@router.get(
    "/infrastructure/upload-types",
    summary="What can be bulk-uploaded, with its columns",
    tags=["Infrastructure Upload"],
)
async def list_upload_types(
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("infrastructure.view")),
):
    """Every upload type with its required and optional columns and accepted formats.

    The upload page renders from this list, so adding a type needs no frontend change.
    """
    from app.modules.infrastructure.upload_service import ASSET_COLUMNS_KEYS, REQUIRED_COLUMNS, get_upload_schema_snapshot
    from app.modules.network.upload import upload_type_specs
    legacy = []
    for key, (label, desc) in _LEGACY_UPLOAD_TYPES.items():
        snapshot = await get_upload_schema_snapshot(db, key, caller.tenant_id)
        configured = [field for field in (snapshot or []) if field.get("field_key")]
        columns = list(dict.fromkeys([*ASSET_COLUMNS_KEYS[key], *(str(field["field_key"]) for field in configured)]))
        required = list(dict.fromkeys([
            *REQUIRED_COLUMNS[key],
            *(str(field["field_key"]) for field in configured if field.get("is_required") or (field.get("validation_rules") or {}).get("required")),
        ]))
        legacy.append({
            "key": key, "label": label, "description": desc, "group": "register", "kind": "asset",
            "asset_type": key.upper() if key != "splitter" else "SPLITTER",
            "formats": ["xlsx"],
            "required_columns": required,
            "optional_columns": [c for c in columns if c not in required],
            "geojson_geometry": None,
        })
    return {"success": True, "data": legacy + upload_type_specs()}


@router.get(
    "/infrastructure/upload-types/{asset_type}/template",
    summary="Download an Excel template for an upload type",
    tags=["Infrastructure Upload"],
)
async def download_upload_template(
    asset_type: str,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("infrastructure.view")),
):
    import io

    import openpyxl
    from app.modules.infrastructure.upload_service import ASSET_COLUMNS_DISPLAY, get_upload_schema_snapshot
    from app.modules.network.upload import NET_UPLOAD_TYPES, template_xlsx
    if asset_type in NET_UPLOAD_TYPES:
        buf = template_xlsx(NET_UPLOAD_TYPES[asset_type])
    elif asset_type in _LEGACY_UPLOAD_TYPES:
        snapshot = await get_upload_schema_snapshot(db, asset_type, caller.tenant_id)
        columns = list(dict.fromkeys([
            *ASSET_COLUMNS_DISPLAY[asset_type],
            *(str(field.get("field_key")) for field in (snapshot or []) if field.get("field_key")),
        ]))
        wb = openpyxl.Workbook()
        wb.active.append(columns)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
    else:
        raise HTTPException(status_code=404, detail=f"Unknown upload type '{asset_type}'")
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="opsyn_{asset_type}_template.xlsx"'},
    )


@router.post(
    "/infrastructure/upload/{asset_type}",
    status_code=status.HTTP_201_CREATED,
    summary="Upload FTTH asset xlsx for bulk creation",
    tags=["Infrastructure Upload"],
)
async def upload_asset_file(
    asset_type: str,
    file: UploadFile = File(..., description="xlsx file (max 10 MB); network types also take GeoJSON"),
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("infrastructure.edit")),
):
    """Upload an Excel (.xlsx) file to bulk-create FTTH assets.

    Runs four-layer validation (file → headers → rows → DB duplicate check).
    Returns a `ValidationSummary`; check `status` ('validated' | 'failed')
    and `error_rows` before proceeding to commit.
    """
    if asset_type not in _VALID_UPLOAD_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid asset_type '{asset_type}'. Must be one of: {', '.join(sorted(_VALID_UPLOAD_TYPES))}",
        )

    file_bytes = await file.read()

    # Create session record so run_full_validation has a session_id to reference
    session_obj = InfraUploadSession(
        tenant_id=caller.tenant_id,
        asset_type=asset_type,
        status="pending",
        original_filename=file.filename or "upload.xlsx",
        submitted_by=caller.id,
        submitted_at=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(session_obj)
    await db.flush()

    summary = await run_full_validation(
        db,
        session_id=session_obj.id,
        asset_type=asset_type,
        file_bytes=file_bytes,
        tenant_id=caller.tenant_id,
        filename=file.filename or "upload.xlsx",
    )
    await db.commit()
    return summary


@router.get(
    "/infrastructure/upload/{session_id}",
    summary="Get upload session status",
    tags=["Infrastructure Upload"],
)
async def get_upload_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("infrastructure.view")),
):
    """Return status and row counts for an upload session."""
    session_obj = await db.get(InfraUploadSession, session_id)
    if session_obj is None or session_obj.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Upload session not found")
    return _upload_session_dict(session_obj)


@router.post(
    "/infrastructure/upload/{session_id}/commit",
    summary="Commit a validated upload session",
    tags=["Infrastructure Upload"],
)
async def commit_upload_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("infrastructure.edit")),
):
    """Commit all valid rows from a 'validated' session into the live asset tables.

    Atomic — either all rows are inserted or none (savepoint rollback on any error).
    Returns `CommitResult` with `status` ('committed' | 'rolled_back').
    """
    session_obj = await db.get(InfraUploadSession, session_id)
    if session_obj is None or session_obj.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Upload session not found")
    if session_obj.status != "validated":
        raise HTTPException(
            status_code=409,
            detail=f"Session status is '{session_obj.status}' — only 'validated' sessions can be committed",
        )

    result = await commit_session(db, session_id, caller.tenant_id, caller.id)
    await db.commit()
    return result


@router.get(
    "/infrastructure/upload/{session_id}/error-report",
    summary="Download validation error report as xlsx",
    tags=["Infrastructure Upload"],
)
async def download_error_report(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("infrastructure.view")),
):
    """Stream a downloadable xlsx error report for the given upload session.

    Columns: all original asset columns + 'Errors' column with pipe-separated messages.
    """
    session_obj = await db.get(InfraUploadSession, session_id)
    if session_obj is None or session_obj.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Upload session not found")

    buf = await generate_error_report_xlsx(db, session_id)
    buf.seek(0)
    fname = f"errors_{session_obj.asset_type}_{session_id}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _upload_session_dict(s: InfraUploadSession) -> dict:
    return {
        "id": str(s.id),
        "tenant_id": str(s.tenant_id),
        "asset_type": s.asset_type,
        "status": s.status,
        "original_filename": s.original_filename,
        "total_rows": s.total_rows,
        "valid_rows": s.valid_rows,
        "duplicate_rows": s.duplicate_rows,
        "error_rows": s.error_rows,
        "committed_rows": s.committed_rows,
        "submitted_by": str(s.submitted_by) if s.submitted_by else None,
        "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
        "approved_by": str(s.approved_by) if s.approved_by else None,
        "approved_at": s.approved_at.isoformat() if s.approved_at else None,
        "committed_at": s.committed_at.isoformat() if s.committed_at else None,
    }


# ═══════════════════════════════════════════════════════════════
# FTTH ASSET LISTINGS  (Phase 3)
# GET  /infrastructure/cabinets
# GET  /infrastructure/olts
# GET  /infrastructure/splitters
# ═══════════════════════════════════════════════════════════════

@router.get(
    "/infrastructure/cabinets",
    summary="List FTTH cabinets",
    tags=["Infrastructure Assets"],
)
async def list_cabinets(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("infrastructure.view")),
):
    """Return a paginated list of active (non-deleted) cabinets for the caller's tenant."""
    q = select(Cabinet).where(
        Cabinet.tenant_id == caller.tenant_id,
        Cabinet.is_deleted.is_(False),
    )
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        await db.execute(
            q.order_by(Cabinet.cabinet_id).offset((page - 1) * size).limit(size)
        )
    ).scalars().all()
    return {
        "total": total, "page": page, "size": size,
        "items": [_cabinet_dict(r) for r in rows],
    }


@router.get(
    "/infrastructure/olts",
    summary="List OLTs",
    tags=["Infrastructure Assets"],
)
async def list_olts(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("infrastructure.view")),
):
    """Return a paginated list of active (non-deleted) OLTs for the caller's tenant."""
    q = select(OLT).where(
        OLT.tenant_id == caller.tenant_id,
        OLT.is_deleted.is_(False),
    )
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        await db.execute(
            q.order_by(OLT.name).offset((page - 1) * size).limit(size)
        )
    ).scalars().all()
    return {
        "total": total, "page": page, "size": size,
        "items": [_olt_dict(r) for r in rows],
    }


@router.get(
    "/infrastructure/splitters",
    summary="List splitter boxes",
    tags=["Infrastructure Assets"],
)
async def list_splitters(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    splitter_level: Optional[str] = Query(None, description="Filter by 'First-Level' or 'Second-Level'"),
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("infrastructure.view")),
):
    """Return a paginated list of active (non-deleted) splitter boxes for the caller's tenant."""
    q = select(SplitterBox).where(
        SplitterBox.tenant_id == caller.tenant_id,
        SplitterBox.is_deleted.is_(False),
    )
    if splitter_level:
        q = q.where(SplitterBox.splitter_level == splitter_level)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        await db.execute(
            q.order_by(SplitterBox.box_id).offset((page - 1) * size).limit(size)
        )
    ).scalars().all()
    return {
        "total": total, "page": page, "size": size,
        "items": [_splitter_dict(r) for r in rows],
    }


def _cabinet_dict(c: Cabinet) -> dict:
    return {
        "id": str(c.id),
        "cabinet_id": c.cabinet_id,
        "capacity": c.capacity,
        "number_tray": c.number_tray,
        "custom_data": c.custom_data or {},
        "longitude": c.longitude,
        "latitude": c.latitude,
        "created_by": str(c.created_by) if c.created_by else None,
        "upload_session_id": str(c.upload_session_id) if c.upload_session_id else None,
        "created_at": c.created_at.isoformat(),
    }


def _olt_dict(o: OLT) -> dict:
    return {
        "id": str(o.id),
        "name": o.name,
        "location_description": o.location_description,
        "number_of_odf": o.number_of_odf,
        "custom_data": o.custom_data or {},
        "longitude": o.longitude,
        "latitude": o.latitude,
        "created_by": str(o.created_by) if o.created_by else None,
        "upload_session_id": str(o.upload_session_id) if o.upload_session_id else None,
        "created_at": o.created_at.isoformat(),
    }


def _splitter_dict(s: SplitterBox) -> dict:
    return {
        "id": str(s.id),
        "box_id": s.box_id,
        "input_ports": s.input_ports,
        "output_ports": s.output_ports,
        "splitter_level": s.splitter_level,
        "splitter_type": s.splitter_type,
        "number_customer": s.number_customer,
        "custom_data": s.custom_data or {},
        "longitude": s.longitude,
        "latitude": s.latitude,
        "parent_splitter_id": str(s.parent_splitter_id) if s.parent_splitter_id else None,
        "cabinet_id": str(s.cabinet_id) if s.cabinet_id else None,
        "created_by": str(s.created_by) if s.created_by else None,
        "upload_session_id": str(s.upload_session_id) if s.upload_session_id else None,
        "created_at": s.created_at.isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# FTTH ASSET DELETION WORKFLOW  (Phase 4)
# POST  /infrastructure/deletion/{asset_type}          — validate + match
# GET   /infrastructure/deletion/{session_id}          — session status
# POST  /infrastructure/deletion/{session_id}/execute  — execute soft-deletes
# ═══════════════════════════════════════════════════════════════

_VALID_DELETION_TYPES = frozenset({"splitter", "cabinet", "olt"})

_MATCH_FUNCTIONS = {
    "splitter": match_deletion_keys_splitter,
    "cabinet":  match_deletion_keys_cabinet,
    "olt":      match_deletion_keys_olt,
}


@router.post(
    "/infrastructure/deletion/{asset_type}",
    status_code=status.HTTP_201_CREATED,
    summary="Upload deletion file — validate and preview matches",
    tags=["Infrastructure Deletion"],
)
async def upload_deletion_file(
    asset_type: str,
    file: UploadFile = File(..., description="xlsx deletion file (max 10 MB)"),
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("infrastructure.edit")),
):
    """Upload an xlsx deletion file for bulk soft-delete of FTTH assets.

    Validates the file format, parses deletion keys, then matches each key
    against live (non-deleted) records in the database.  Returns a deletion
    session with a full match preview — check `matched_rows` and
    `unmatched_rows` before calling the execute endpoint.
    """
    if asset_type not in _VALID_DELETION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid asset_type '{asset_type}'. Must be one of: {', '.join(sorted(_VALID_DELETION_TYPES))}",
        )

    file_bytes = await file.read()
    filename   = file.filename or "deletion.xlsx"

    # Layer 1: file format + header validation
    validation = await validate_deletion_file(asset_type, file_bytes, filename)
    if not validation.valid:
        raise HTTPException(
            status_code=422,
            detail={"errors": validation.errors},
        )

    # Layer 2: match parsed keys against live DB records (tenant-scoped)
    match_fn = _MATCH_FUNCTIONS[asset_type]
    match_results = await match_fn(db, validation.keys, caller.tenant_id)

    matched_count   = sum(1 for r in match_results if r.status == "matched")
    unmatched_count = sum(1 for r in match_results if r.status == "unmatched")

    # Serialise match details for JSONB storage
    match_details = [
        {
            "key":      r.key,
            "status":   r.status,
            "asset_id": str(r.asset_id) if r.asset_id else None,
            "reason":   r.reason,
        }
        for r in match_results
    ]

    # Layer 3: what execute will take with it. Deleting a cabinet or a
    # First-Level splitter also removes the splitters mounted in / below it,
    # so the approver has to see those before confirming.
    matched_ids = [r.asset_id for r in match_results if r.status == "matched" and r.asset_id]
    _, cascade_ids = await collect_cascade_targets(
        db, asset_type, matched_ids, caller.tenant_id
    )
    cascade_preview: list[dict] = []
    if cascade_ids:
        parent_names = {
            r.asset_id: r.key.get("cabinet_id") or r.key.get("box_id") or ""
            for r in match_results if r.asset_id
        }
        cascade_rows = (await db.execute(
            select(
                SplitterBox.id, SplitterBox.box_id,
                SplitterBox.parent_splitter_id, SplitterBox.cabinet_id,
            ).where(SplitterBox.id.in_(cascade_ids))
        )).all()
        root_ids = set(matched_ids)
        for row in cascade_rows:
            parent_key = (
                parent_names.get(row.parent_splitter_id)
                or parent_names.get(row.cabinet_id)
                or (row.parent_splitter_id or row.cabinet_id)
            )
            cascade_preview.append({
                "asset_id":   str(row.id),
                "asset_key":  row.box_id,
                "parent_key": str(parent_key) if parent_key else None,
                "from_match": row.id in root_ids,
            })

    # Create deletion session
    session_obj = InfraDeletionSession(
        tenant_id=caller.tenant_id,
        asset_type=asset_type,
        status="pending",
        original_filename=filename,
        total_rows=validation.total_rows,
        matched_rows=matched_count,
        unmatched_rows=unmatched_count,
        deleted_rows=None,
        cascaded_rows=len(cascade_preview),
        cascade_preview=cascade_preview,
        match_details=match_details,
        submitted_by=caller.id,
        submitted_at=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(session_obj)
    await db.commit()
    await db.refresh(session_obj)

    return _deletion_session_dict(session_obj)


@router.get(
    "/infrastructure/deletion/{session_id}",
    summary="Get deletion session status and match details",
    tags=["Infrastructure Deletion"],
)
async def get_deletion_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("infrastructure.view")),
):
    """Return status and match preview for a deletion session."""
    session_obj = await db.get(InfraDeletionSession, session_id)
    if session_obj is None or session_obj.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Deletion session not found")
    return _deletion_session_dict(session_obj)


@router.post(
    "/infrastructure/deletion/{session_id}/execute",
    summary="Execute a pending deletion session",
    tags=["Infrastructure Deletion"],
)
async def execute_deletion_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("infrastructure.edit")),
):
    """Soft-delete all matched assets from a 'pending' deletion session.

    Atomic — either all matched assets are soft-deleted or none
    (savepoint rollback on any DB error).  Returns `DeletionResult`
    with `status` ('executed' | 'failed').
    """
    session_obj = await db.get(InfraDeletionSession, session_id)
    if session_obj is None or session_obj.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Deletion session not found")
    if session_obj.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Session status is '{session_obj.status}' — only 'pending' sessions can be executed",
        )

    result = await execute_deletion(db, session_id, caller.tenant_id, caller.id)
    await db.commit()
    return result


def _deletion_session_dict(s: InfraDeletionSession) -> dict:
    return {
        "id":                str(s.id),
        "tenant_id":         str(s.tenant_id),
        "asset_type":        s.asset_type,
        "status":            s.status,
        "original_filename": s.original_filename,
        "total_rows":        s.total_rows,
        "matched_rows":      s.matched_rows,
        "unmatched_rows":    s.unmatched_rows,
        "deleted_rows":      s.deleted_rows,
        "cascaded_rows":     s.cascaded_rows,
        "cascade_preview":   s.cascade_preview or [],
        "total_effective":   (s.deleted_rows if s.deleted_rows is not None
                              else (s.matched_rows or 0)) + (s.cascaded_rows or 0),
        "match_details":     s.match_details or [],
        "submitted_by":      str(s.submitted_by) if s.submitted_by else None,
        "submitted_at":      s.submitted_at.isoformat() if s.submitted_at else None,
        "approved_by":       str(s.approved_by) if s.approved_by else None,
        "approved_at":       s.approved_at.isoformat() if s.approved_at else None,
        "executed_at":       s.executed_at.isoformat() if s.executed_at else None,
    }


# ═══════════════════════════════════════════════════════════════
# FTTH AUDIT LOG  (Phase 7)
# GET  /infrastructure/audit
# GET  /infrastructure/audit/{entry_id}
# ═══════════════════════════════════════════════════════════════

@router.get(
    "/infrastructure/audit",
    summary="Query FTTH asset audit log",
    tags=["Infrastructure Audit"],
)
async def list_infra_audit_log(
    page:        int            = Query(1, ge=1),
    size:        int            = Query(50, ge=1, le=200),
    asset_type:  Optional[str]  = Query(None, description="Filter by 'splitter', 'cabinet', or 'olt'"),
    action:      Optional[str]  = Query(None, description="Filter by action: 'upload', 'soft_delete'"),
    asset_key:   Optional[str]  = Query(None, description="Filter by asset key (box_id / cabinet_id / OLT name)"),
    session_id:  Optional[uuid.UUID] = Query(None, description="Filter by upload or deletion session UUID"),
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("infrastructure.view")),
):
    """Return a paginated, filterable audit log for FTTH asset changes.

    Entries are written by the upload commit and deletion execute workflows.
    Each entry records the actor, action, asset key, and a full before/after
    snapshot of the asset data.
    """
    q = select(InfraAuditLog).where(InfraAuditLog.tenant_id == caller.tenant_id)

    if asset_type:
        q = q.where(InfraAuditLog.asset_type == asset_type)
    if action:
        q = q.where(InfraAuditLog.action == action)
    if asset_key:
        q = q.where(InfraAuditLog.asset_key == asset_key)
    if session_id:
        q = q.where(InfraAuditLog.session_id == session_id)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows  = (
        await db.execute(
            q.order_by(InfraAuditLog.timestamp.desc())
             .offset((page - 1) * size)
             .limit(size)
        )
    ).scalars().all()

    return {
        "total": total,
        "page":  page,
        "size":  size,
        "items": [_audit_log_dict(r) for r in rows],
    }


@router.get(
    "/infrastructure/audit/{entry_id}",
    summary="Get a single audit log entry with full data snapshots",
    tags=["Infrastructure Audit"],
)
async def get_infra_audit_entry(
    entry_id: uuid.UUID,
    db:       AsyncSession = Depends(get_db),
    caller:   User         = Depends(check_permission("infrastructure.view")),
):
    """Return a single audit log entry including old_data and new_data snapshots."""
    entry = await db.get(InfraAuditLog, entry_id)
    if entry is None or entry.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Audit log entry not found")
    return _audit_log_dict(entry, include_snapshots=True)


def _audit_log_dict(e: InfraAuditLog, include_snapshots: bool = False) -> dict:
    d: dict = {
        "id":          str(e.id),
        "asset_type":  e.asset_type,
        "asset_id":    str(e.asset_id)   if e.asset_id   else None,
        "asset_key":   e.asset_key,
        "action":      e.action,
        "session_id":  str(e.session_id) if e.session_id else None,
        "actor_id":    str(e.actor_id)   if e.actor_id   else None,
        "actor_label": e.actor_label,
        "timestamp":   e.timestamp.isoformat() if e.timestamp else None,
    }
    if include_snapshots:
        d["old_data"] = e.old_data
        d["new_data"] = e.new_data
    return d
