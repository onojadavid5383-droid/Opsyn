# ============================================================
# OPSYN NETWORK CABLE SERVICE — app/modules/network/cable_service.py
#
# Reads and writes for live cables (net_cables, design_id IS NULL).
# Same rules as the asset service: explicit tenant filter on top of RLS,
# lifecycle moves only along lifecycle.TRANSITIONS, soft delete, every
# write audited ("net_cable:<CATEGORY>").
#
# Geometry: length_m is never taken from the client — the net_cables_length
# trigger recomputes it from geom. Road-graph routing does not exist yet
# (Phase 4 routing service), so a line supplied here is either as-built
# (IMPORTED) or hand-drawn (MANUAL_GEOMETRY); editing the line of any cable
# makes it MANUAL_GEOMETRY, because it no longer follows the computed route.
# ============================================================

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.infrastructure.audit_service import write_audit_entry
from app.modules.network.attributes import CABLE_ATTRIBUTES
from app.modules.network.codes import next_codes
from app.modules.network.topology import sync_derived_connections
from app.modules.network.lifecycle import MANUAL_DEFAULT_STATE, TRANSITIONS, can_transition
from app.modules.network.models import NetCable
from app.modules.network.schemas import AssetRef, CableCreate, CableOut, CableSummary, CableUpdate
from app.modules.network.service import (
    _iso, _uuid_or_404, _uuid_or_422, checked_attributes, escape_like,
)

_LIVE = "c.tenant_id = :tid AND c.deleted_at IS NULL AND c.design_id IS NULL"


def _line_ewkt(coords: list[list[float]]) -> str:
    return "SRID=4326;LINESTRING(" + ", ".join(f"{x} {y}" for x, y in coords) + ")"


async def _check_endpoint(db: AsyncSession, tid: uuid.UUID, asset_id: uuid.UUID | None, which: str) -> None:
    if asset_id is None:
        return
    ok = (await db.execute(text("""
        SELECT 1 FROM net_assets
        WHERE id = :id AND tenant_id = :tid AND deleted_at IS NULL AND design_id IS NULL
    """), {"id": asset_id, "tid": tid})).first()
    if ok is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"The {which} asset is not in the live network")


async def list_cables(db: AsyncSession, tid: uuid.UUID, *, categories: list[str] | None,
                      statuses: list[str] | None, q: str | None, page: int, size: int
                      ) -> tuple[list[CableSummary], int]:
    where = [_LIVE]
    params: dict[str, Any] = {"tid": tid}
    if categories:
        where.append("c.cable_category = ANY(:cats)")
        params["cats"] = categories
    if statuses:
        where.append("c.lifecycle_status = ANY(:statuses)")
        params["statuses"] = statuses
    if q and q.strip():
        where.append("(c.asset_code ILIKE :like OR c.name ILIKE :like)")
        params["like"] = f"%{escape_like(q.strip())}%"
    clause = " AND ".join(where)
    total = (await db.execute(text(f"SELECT count(*) FROM net_cables c WHERE {clause}"), params)).scalar_one()
    rows = (await db.execute(text(f"""
        SELECT c.id, c.asset_code, c.cable_category, c.name, c.lifecycle_status,
               c.length_m::float8 AS length_m, c.fiber_count
        FROM net_cables c WHERE {clause}
        ORDER BY c.cable_category, c.asset_code
        LIMIT :limit OFFSET :offset
    """), {**params, "limit": size, "offset": (page - 1) * size})).all()
    return [CableSummary(id=str(r.id), asset_code=r.asset_code, cable_category=r.cable_category, name=r.name,
                         lifecycle_status=r.lifecycle_status, length_m=r.length_m, fiber_count=r.fiber_count)
            for r in rows], total


async def get_cable(db: AsyncSession, tid: uuid.UUID, cable_id: str) -> CableOut:
    cid = _uuid_or_404(cable_id, "Cable")
    r = (await db.execute(text(f"""
        SELECT c.*, c.length_m::float8 AS length_f,
               ST_AsGeoJSON(c.geom, 7) AS geojson,
               ST_X(ST_LineInterpolatePoint(c.geom, 0.5)) AS mid_x,
               ST_Y(ST_LineInterpolatePoint(c.geom, 0.5)) AS mid_y,
               ST_XMin(c.geom) AS x1, ST_YMin(c.geom) AS y1, ST_XMax(c.geom) AS x2, ST_YMax(c.geom) AS y2,
               s.id AS s_id, s.asset_code AS s_code, s.asset_type AS s_type, s.name AS s_name,
               d.id AS d_id, d.asset_code AS d_code, d.asset_type AS d_type, d.name AS d_name
        FROM net_cables c
        LEFT JOIN net_assets s ON s.id = c.source_asset_id AND s.deleted_at IS NULL
        LEFT JOIN net_assets d ON d.id = c.dest_asset_id   AND d.deleted_at IS NULL
        WHERE c.id = :id AND {_LIVE}
    """), {"id": cid, "tid": tid})).mappings().first()
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cable not found")

    def ref(prefix: str) -> AssetRef | None:
        if r[f"{prefix}_id"] is None:
            return None
        return AssetRef(id=str(r[f"{prefix}_id"]), asset_code=r[f"{prefix}_code"],
                        asset_type=r[f"{prefix}_type"], name=r[f"{prefix}_name"])

    return CableOut(
        id=str(r["id"]), asset_code=r["asset_code"], cable_category=r["cable_category"],
        name=r["name"], description=r["description"], lifecycle_status=r["lifecycle_status"],
        creation_method=r["creation_method"], route_method=r["route_method"],
        installation_type=r["installation_type"], fiber_count=r["fiber_count"], length_m=r["length_f"],
        geometry=json.loads(r["geojson"]), midpoint=[float(r["mid_x"]), float(r["mid_y"])],
        bbox=[float(r["x1"]), float(r["y1"]), float(r["x2"]), float(r["y2"])],
        source=ref("s"), dest=ref("d"), attributes=r["attributes"] or {},
        project_id=str(r["project_id"]) if r["project_id"] else None,
        design_id=str(r["design_id"]) if r["design_id"] else None,
        lineage_id=str(r["lineage_id"]), source_table=r["source_table"],
        allowed_transitions=sorted(TRANSITIONS.get(r["lifecycle_status"], ())),
        created_at=_iso(r["created_at"]), updated_at=_iso(r["updated_at"]),
    )


def _snapshot(c: NetCable) -> dict[str, Any]:
    return {
        "asset_code": c.asset_code, "cable_category": c.cable_category, "name": c.name,
        "lifecycle_status": c.lifecycle_status, "route_method": c.route_method,
        "fiber_count": c.fiber_count, "installation_type": c.installation_type,
        "source_asset_id": str(c.source_asset_id) if c.source_asset_id else None,
        "dest_asset_id": str(c.dest_asset_id) if c.dest_asset_id else None,
        "attributes": c.attributes,
    }


def _duplicate(exc: IntegrityError) -> bool:
    return "uq_net_cables_live_code" in str(exc.orig)


async def create_cable(db: AsyncSession, tid: uuid.UUID, caller: Any, body: CableCreate) -> CableOut:
    src = _uuid_or_422(body.source_asset_id, "source_asset_id")
    dst = _uuid_or_422(body.dest_asset_id, "dest_asset_id")
    await _check_endpoint(db, tid, src, "source")
    await _check_endpoint(db, tid, dst, "destination")
    attributes = checked_attributes(CABLE_ATTRIBUTES, body.attributes)
    code = body.asset_code or (await next_codes(db, tid, "cable", body.cable_category))[0]
    cable = NetCable(
        tenant_id=tid, asset_code=code, cable_category=body.cable_category,
        name=body.name, description=body.description,
        geom=_line_ewkt(body.geometry.coordinates),
        route_method=body.route_method, fiber_count=body.fiber_count,
        installation_type=body.installation_type,
        lifecycle_status=body.lifecycle_status or MANUAL_DEFAULT_STATE,
        creation_method="IMPORTED" if body.route_method == "IMPORTED" else "MANUAL",
        source_asset_id=src, dest_asset_id=dst, attributes=attributes,
        created_by=caller.id, updated_by=caller.id,
    )
    try:
        # A savepoint around the INSERT only (see service.create_asset)
        async with db.begin_nested():
            db.add(cable)
            await db.flush()
    except IntegrityError as exc:
        if _duplicate(exc):
            raise HTTPException(status.HTTP_409_CONFLICT, f"A live cable with code '{code}' already exists")
        raise
    await write_audit_entry(
        db, asset_type=f"net_cable:{cable.cable_category}", asset_id=cable.id, asset_key=cable.asset_code,
        action="create", actor_user=caller, new_data=_snapshot(cable), tenant_id=tid,
    )
    await sync_derived_connections(db, tid)
    return await get_cable(db, tid, str(cable.id))


async def _load_live(db: AsyncSession, tid: uuid.UUID, cable_id: str) -> NetCable:
    cable = await db.get(NetCable, _uuid_or_404(cable_id, "Cable"))
    if cable is None or cable.tenant_id != tid or cable.deleted_at is not None or cable.design_id is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cable not found")
    return cable


async def update_cable(db: AsyncSession, tid: uuid.UUID, caller: Any, cable_id: str, body: CableUpdate) -> CableOut:
    cable = await _load_live(db, tid, cable_id)
    before = _snapshot(cable)
    sent = body.model_fields_set

    if "lifecycle_status" in sent and body.lifecycle_status and body.lifecycle_status != cable.lifecycle_status:
        if not can_transition(cable.lifecycle_status, body.lifecycle_status):
            allowed = ", ".join(sorted(TRANSITIONS[cable.lifecycle_status])) or "none"
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Cannot move from {cable.lifecycle_status} to {body.lifecycle_status}. "
                                f"Allowed next states: {allowed}")
        cable.lifecycle_status = body.lifecycle_status
    for which, field in (("source", "source_asset_id"), ("destination", "dest_asset_id")):
        if field in sent:
            ref = _uuid_or_422(getattr(body, field), field)
            await _check_endpoint(db, tid, ref, which)
            setattr(cable, field, ref)
    for field in ("asset_code", "name", "description", "fiber_count", "installation_type"):
        if field in sent:
            value = getattr(body, field)
            if field == "asset_code" and value is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "asset code cannot be removed")
            setattr(cable, field, value)
    if "attributes" in sent and body.attributes is not None:
        cable.attributes = checked_attributes(CABLE_ATTRIBUTES, body.attributes, cable.attributes)
    if "geometry" in sent and body.geometry is not None:
        cable.geom = _line_ewkt(body.geometry.coordinates)
        cable.route_method = "MANUAL_GEOMETRY"

    cable.updated_by = caller.id
    cable.updated_at = datetime.datetime.now(datetime.timezone.utc)
    # The UPDATE is already pending: find a code clash by query first, without
    # letting the pending UPDATE reach the table (no_autoflush); a refused code
    # is put back, so nothing stays pending.
    if "asset_code" in sent:
        with db.no_autoflush:               # a sync context manager
            clash = (await db.execute(text(f"""
                SELECT 1 FROM net_cables c WHERE {_LIVE} AND c.asset_code = :code AND c.id <> :id
            """), {"tid": tid, "code": cable.asset_code, "id": cable.id})).first()
        if clash:
            refused, cable.asset_code = cable.asset_code, before["asset_code"]
            raise HTTPException(status.HTTP_409_CONFLICT, f"Another live cable already uses code '{refused}'")
    try:
        await db.flush()
    except IntegrityError as exc:           # a race the check above could not see
        if _duplicate(exc):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Another live cable already uses code '{cable.asset_code}'")
        raise
    await write_audit_entry(
        db, asset_type=f"net_cable:{cable.cable_category}", asset_id=cable.id, asset_key=cable.asset_code,
        action="update", actor_user=caller, old_data=before, new_data=_snapshot(cable), tenant_id=tid,
    )
    await sync_derived_connections(db, tid)
    return await get_cable(db, tid, str(cable.id))


async def delete_cable(db: AsyncSession, tid: uuid.UUID, caller: Any, cable_id: str) -> None:
    cable = await _load_live(db, tid, cable_id)
    now = datetime.datetime.now(datetime.timezone.utc)
    cable.deleted_at = now
    cable.deleted_by = caller.id
    cable.updated_at = now
    await db.flush()
    await write_audit_entry(
        db, asset_type=f"net_cable:{cable.cable_category}", asset_id=cable.id, asset_key=cable.asset_code,
        action="soft_delete", actor_user=caller, old_data=_snapshot(cable), tenant_id=tid,
    )
    await sync_derived_connections(db, tid)
