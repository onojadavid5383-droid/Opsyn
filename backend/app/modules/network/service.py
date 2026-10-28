# ============================================================
# OPSYN NETWORK SERVICE — app/modules/network/service.py
#
# Reads and writes for live network assets (design_id IS NULL).
# Design working sets get their own service in Phase 4.
#
# Tenant isolation is enforced twice: get_db() sets app.tenant_id for RLS,
# and every query here also filters tenant_id explicitly. The RLS policy
# lets a session with no tenant set see every row (the migration/worker
# path), so the explicit filter is what protects a misconfigured request.
#
# Every write is recorded in infrastructure_audit_log with asset_type
# "net_asset:<TYPE>" — the generalised network audit trail is Phase 8.
# ============================================================

from __future__ import annotations

import datetime
import json
import re
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.infrastructure.audit_service import write_audit_entry
from app.modules.network.asset_types import ASSET_TYPES
from app.modules.network.attributes import FieldSpec, asset_specs, validate_attributes
from app.modules.network.codes import next_codes
from app.modules.network.topology import sync_derived_connections
from app.modules.network.lifecycle import (
    LIVE_STATES, MANUAL_DEFAULT_STATE, TRANSITIONS, can_transition,
)
from app.modules.network.models import NetAsset
from app.modules.network.schemas import (
    AssetCreate, AssetOut, AssetRef, AssetSummary, AssetUpdate,
)

MAX_PAGE_SIZE = 200
MAX_SEARCH_RESULTS = 50

# Columns every read needs; the point is the representative position
# used for labels, fly-to and the inspector (assets are points today).
_ASSET_COLUMNS = """
    a.id, a.asset_code, a.asset_type, a.name, a.description,
    a.lifecycle_status, a.creation_method, a.attributes,
    a.capacity, a.used_capacity, a.parent_id, a.project_id, a.design_id,
    a.lineage_id, a.source_table, a.created_at, a.updated_at,
    ST_AsGeoJSON(a.geom, 7)                AS geojson,
    ST_X(ST_PointOnSurface(a.geom))        AS lng,
    ST_Y(ST_PointOnSurface(a.geom))        AS lat
"""

_LIVE_SCOPE = "a.tenant_id = :tid AND a.deleted_at IS NULL AND a.design_id IS NULL"


def _uuid_or_404(value: str, what: str = "Asset") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


def _uuid_or_422(value: str | None, field: str) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} is not a valid id")


def _iso(dt: datetime.datetime | None) -> str:
    return dt.isoformat() if dt else ""


def _summary(r: Any) -> AssetSummary:
    return AssetSummary(
        id=str(r.id), asset_code=r.asset_code, asset_type=r.asset_type, name=r.name,
        lifecycle_status=r.lifecycle_status, lng=float(r.lng), lat=float(r.lat),
    )


def escape_like(q: str) -> str:
    """Escape LIKE wildcards so user input matches literally."""
    return re.sub(r"([\\%_])", r"\\\1", q)


def checked_attributes(specs: tuple[FieldSpec, ...], new: dict[str, Any],
                       old: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate attributes against a type's spec, or 422 with every problem.

    On update only the keys whose value changed are checked: a value that
    arrived by import in an older shape must not block an unrelated edit.
    """
    old = old or {}
    changed = {k: v for k, v in new.items() if k not in old or old[k] != v}
    clean, errors = validate_attributes(specs, changed)
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "; ".join(e["error"] for e in errors))
    unchanged = {k: v for k, v in new.items() if k not in changed}
    return {**unchanged, **clean}


def parse_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    """'minLng,minLat,maxLng,maxLat' → tuple, or 422."""
    if not bbox:
        return None
    try:
        parts = [float(p) for p in bbox.split(",")]
    except ValueError:
        parts = []
    if len(parts) != 4:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "bbox must be 'minLng,minLat,maxLng,maxLat'")
    min_lng, min_lat, max_lng, max_lat = parts
    if not (-180 <= min_lng < max_lng <= 180 and -90 <= min_lat < max_lat <= 90):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "bbox is out of range or inverted")
    return min_lng, min_lat, max_lng, max_lat


# ── Reads ────────────────────────────────────────────────────

async def list_assets(
    db: AsyncSession, tid: uuid.UUID, *,
    types: list[str] | None, statuses: list[str] | None,
    bbox: tuple[float, float, float, float] | None,
    page: int, size: int, q: str | None = None,
) -> tuple[list[AssetSummary], int]:
    where = [_LIVE_SCOPE]
    params: dict[str, Any] = {"tid": tid}
    if q and q.strip():
        where.append("(a.asset_code ILIKE :like OR a.name ILIKE :like)")
        params["like"] = f"%{escape_like(q.strip())}%"
    if types:
        where.append("a.asset_type = ANY(:types)")
        params["types"] = types
    if statuses:
        where.append("a.lifecycle_status = ANY(:statuses)")
        params["statuses"] = statuses
    if bbox:
        where.append("a.geom && ST_MakeEnvelope(:x1, :y1, :x2, :y2, 4326)")
        params.update(x1=bbox[0], y1=bbox[1], x2=bbox[2], y2=bbox[3])
    clause = " AND ".join(where)

    total = (await db.execute(text(f"SELECT count(*) FROM net_assets a WHERE {clause}"), params)).scalar_one()
    rows = (await db.execute(text(f"""
        SELECT {_ASSET_COLUMNS} FROM net_assets a
        WHERE {clause}
        ORDER BY a.asset_type, a.asset_code
        LIMIT :limit OFFSET :offset
    """), {**params, "limit": size, "offset": (page - 1) * size})).all()
    return [_summary(r) for r in rows], total


async def get_asset(db: AsyncSession, tid: uuid.UUID, asset_id: str) -> AssetOut:
    aid = _uuid_or_404(asset_id)
    r = (await db.execute(text(f"""
        SELECT {_ASSET_COLUMNS},
               p.id AS p_id, p.asset_code AS p_code, p.asset_type AS p_type, p.name AS p_name,
               (SELECT count(*) FROM net_assets c
                WHERE c.parent_id = a.id AND c.deleted_at IS NULL) AS children_count
        FROM net_assets a
        LEFT JOIN net_assets p ON p.id = a.parent_id AND p.deleted_at IS NULL
        WHERE a.id = :id AND {_LIVE_SCOPE}
    """), {"id": aid, "tid": tid})).first()
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    return AssetOut(
        id=str(r.id), asset_code=r.asset_code, asset_type=r.asset_type, name=r.name,
        description=r.description, lifecycle_status=r.lifecycle_status,
        creation_method=r.creation_method, geometry=json.loads(r.geojson),
        lng=float(r.lng), lat=float(r.lat), attributes=r.attributes or {},
        capacity=r.capacity, used_capacity=r.used_capacity,
        parent=AssetRef(id=str(r.p_id), asset_code=r.p_code, asset_type=r.p_type, name=r.p_name) if r.p_id else None,
        children_count=int(r.children_count or 0),
        project_id=str(r.project_id) if r.project_id else None,
        design_id=str(r.design_id) if r.design_id else None,
        lineage_id=str(r.lineage_id), source_table=r.source_table,
        allowed_transitions=sorted(TRANSITIONS.get(r.lifecycle_status, ())),
        created_at=_iso(r.created_at), updated_at=_iso(r.updated_at),
    )


async def search_assets(
    db: AsyncSession, tid: uuid.UUID, q: str, *,
    field: str = "any", asset_type: str | None = None, limit: int = 20,
) -> list[AssetSummary]:
    """Live-network search by code and/or name.

    Only assets the NETWORK map shows (live lifecycle states) are returned,
    so every result can be flown to and selected. Ranking: exact code,
    then prefix, then trigram similarity.
    """
    q = q.strip()
    if not q:
        return []
    like = f"%{escape_like(q)}%"
    prefix = f"{escape_like(q)}%"
    match = {
        "code": "a.asset_code ILIKE :like OR a.asset_code % :q",
        "name": "a.name ILIKE :like OR a.name % :q",
    }.get(field, "a.asset_code ILIKE :like OR a.name ILIKE :like OR a.asset_code % :q OR a.name % :q")
    where = [_LIVE_SCOPE, "a.lifecycle_status = ANY(:live)", f"({match})"]
    params: dict[str, Any] = {
        "tid": tid, "q": q, "like": like, "prefix": prefix,
        "live": list(LIVE_STATES), "limit": min(max(limit, 1), MAX_SEARCH_RESULTS),
    }
    if asset_type:
        where.append("a.asset_type = :type")
        params["type"] = asset_type
    rows = (await db.execute(text(f"""
        SELECT {_ASSET_COLUMNS} FROM net_assets a
        WHERE {' AND '.join(where)}
        ORDER BY (lower(a.asset_code) = lower(:q)) DESC,
                 (a.asset_code ILIKE :prefix OR a.name ILIKE :prefix) DESC,
                 greatest(similarity(a.asset_code, :q), similarity(coalesce(a.name, ''), :q)) DESC,
                 a.asset_code
        LIMIT :limit
    """), params)).all()
    return [_summary(r) for r in rows]


# ── Writes ───────────────────────────────────────────────────

def _audit_snapshot(a: NetAsset, lng: float | None = None, lat: float | None = None) -> dict[str, Any]:
    snap = {
        "asset_code": a.asset_code, "asset_type": a.asset_type, "name": a.name,
        "description": a.description, "lifecycle_status": a.lifecycle_status,
        "capacity": a.capacity, "used_capacity": a.used_capacity,
        "attributes": a.attributes,
        "parent_id": str(a.parent_id) if a.parent_id else None,
        "project_id": str(a.project_id) if a.project_id else None,
    }
    if lng is not None:
        snap["lng"], snap["lat"] = lng, lat
    return snap


async def _load_live(db: AsyncSession, tid: uuid.UUID, asset_id: str) -> NetAsset:
    aid = _uuid_or_404(asset_id)
    asset = await db.get(NetAsset, aid)
    if asset is None or asset.tenant_id != tid or asset.deleted_at is not None or asset.design_id is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    return asset


async def _check_parent(db: AsyncSession, tid: uuid.UUID, parent_id: uuid.UUID | None,
                        self_id: uuid.UUID | None = None) -> None:
    if parent_id is None:
        return
    if parent_id == self_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "An asset cannot contain itself")
    ok = (await db.execute(text(f"""
        SELECT 1 FROM net_assets a WHERE a.id = :pid AND {_LIVE_SCOPE}
    """), {"pid": parent_id, "tid": tid})).first()
    if ok is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Parent asset not found in the live network")
    if self_id is not None:
        # Walking up from the new parent must never reach this asset.
        cycle = (await db.execute(text("""
            WITH RECURSIVE up(id, depth) AS (
                SELECT CAST(:pid AS uuid), 0
                UNION ALL
                SELECT a.parent_id, up.depth + 1 FROM net_assets a
                JOIN up ON a.id = up.id
                WHERE a.parent_id IS NOT NULL AND up.depth < 32
            )
            SELECT 1 FROM up WHERE id = :self LIMIT 1
        """), {"pid": parent_id, "self": self_id})).first()
        if cycle is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "That parent is inside this asset — containment cannot loop")


def _duplicate_code(exc: IntegrityError) -> bool:
    return "uq_net_assets_live_code" in str(exc.orig)


async def create_asset(db: AsyncSession, tid: uuid.UUID, caller: Any, body: AssetCreate) -> AssetOut:
    parent_id = _uuid_or_422(body.parent_id, "parent_id")
    await _check_parent(db, tid, parent_id)
    attributes = checked_attributes(asset_specs(body.asset_type), body.attributes)
    code = body.asset_code or (await next_codes(db, tid, "asset", body.asset_type))[0]
    lng, lat = body.geometry.coordinates
    asset = NetAsset(
        tenant_id=tid, asset_code=code, asset_type=body.asset_type,
        name=body.name, description=body.description,
        geom=f"SRID=4326;POINT({lng} {lat})",
        lifecycle_status=body.lifecycle_status or MANUAL_DEFAULT_STATE,
        creation_method="MANUAL", parent_id=parent_id,
        project_id=_uuid_or_422(body.project_id, "project_id"),
        attributes=attributes, capacity=body.capacity, used_capacity=body.used_capacity,
        created_by=caller.id, updated_by=caller.id,
    )
    try:
        # A savepoint around the INSERT only: a rejected write undoes itself,
        # not the caller's other work (begin_nested flushes anything already
        # pending first, so the add must happen inside it)
        async with db.begin_nested():
            db.add(asset)
            await db.flush()
    except IntegrityError as exc:
        if _duplicate_code(exc):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"A live {ASSET_TYPES[body.asset_type].label} with code '{code}' already exists")
        raise
    await write_audit_entry(
        db, asset_type=f"net_asset:{asset.asset_type}", asset_id=asset.id, asset_key=asset.asset_code,
        action="create", actor_user=caller, new_data=_audit_snapshot(asset, lng, lat), tenant_id=tid,
    )
    await sync_derived_connections(db, tid)
    return await get_asset(db, tid, str(asset.id))


async def update_asset(db: AsyncSession, tid: uuid.UUID, caller: Any, asset_id: str, body: AssetUpdate) -> AssetOut:
    asset = await _load_live(db, tid, asset_id)
    before = _audit_snapshot(asset)
    sent = body.model_fields_set

    if "lifecycle_status" in sent and body.lifecycle_status and body.lifecycle_status != asset.lifecycle_status:
        if not can_transition(asset.lifecycle_status, body.lifecycle_status):
            allowed = ", ".join(sorted(TRANSITIONS[asset.lifecycle_status])) or "none"
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Cannot move from {asset.lifecycle_status} to {body.lifecycle_status}. Allowed next states: {allowed}",
            )
        asset.lifecycle_status = body.lifecycle_status
    if "parent_id" in sent:
        parent_id = _uuid_or_422(body.parent_id, "parent_id")
        await _check_parent(db, tid, parent_id, self_id=asset.id)
        asset.parent_id = parent_id
    if "project_id" in sent:
        asset.project_id = _uuid_or_422(body.project_id, "project_id")
    for field in ("asset_code", "name", "description", "capacity", "used_capacity"):
        if field in sent:
            value = getattr(body, field)
            if field == "asset_code" and value is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "asset code cannot be removed")
            setattr(asset, field, value)
    if "attributes" in sent and body.attributes is not None:
        asset.attributes = checked_attributes(asset_specs(asset.asset_type), body.attributes, asset.attributes)
    lng = lat = None
    if "geometry" in sent and body.geometry is not None:
        lng, lat = body.geometry.coordinates
        asset.geom = f"SRID=4326;POINT({lng} {lat})"

    asset.updated_by = caller.id
    asset.updated_at = datetime.datetime.now(datetime.timezone.utc)
    # The UPDATE is already pending, so a savepoint cannot isolate it: a code
    # clash is found by query first and answered before anything is written.
    # no_autoflush keeps the pending UPDATE out of the table until the clash
    # has been answered; a refused code is put back, so nothing stays pending.
    if "asset_code" in sent:
        with db.no_autoflush:               # a sync context manager
            clash = (await db.execute(text(f"""
                SELECT 1 FROM net_assets a
                WHERE {_LIVE_SCOPE} AND a.asset_type = :type AND a.asset_code = :code AND a.id <> :id
            """), {"tid": tid, "type": asset.asset_type, "code": asset.asset_code, "id": asset.id})).first()
        if clash:
            refused, asset.asset_code = asset.asset_code, before["asset_code"]
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Another live {ASSET_TYPES[asset.asset_type].label} already uses code '{refused}'")
    try:
        await db.flush()
    except IntegrityError as exc:           # a race the check above could not see
        if _duplicate_code(exc):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Another live {ASSET_TYPES[asset.asset_type].label} already uses code '{asset.asset_code}'")
        raise
    await write_audit_entry(
        db, asset_type=f"net_asset:{asset.asset_type}", asset_id=asset.id, asset_key=asset.asset_code,
        action="update", actor_user=caller, old_data=before,
        new_data=_audit_snapshot(asset, lng, lat), tenant_id=tid,
    )
    await sync_derived_connections(db, tid)
    return await get_asset(db, tid, str(asset.id))


async def delete_asset(db: AsyncSession, tid: uuid.UUID, caller: Any, asset_id: str) -> None:
    """Soft delete. Contained assets lose their parent link, never their row."""
    asset = await _load_live(db, tid, asset_id)
    now = datetime.datetime.now(datetime.timezone.utc)
    asset.deleted_at = now
    asset.deleted_by = caller.id
    asset.updated_at = now
    await db.execute(text("""
        UPDATE net_assets SET parent_id = NULL, updated_at = now()
        WHERE parent_id = :id AND tenant_id = :tid
    """), {"id": asset.id, "tid": tid})
    await db.flush()
    await write_audit_entry(
        db, asset_type=f"net_asset:{asset.asset_type}", asset_id=asset.id, asset_key=asset.asset_code,
        action="soft_delete", actor_user=caller, old_data=_audit_snapshot(asset), tenant_id=tid,
    )
    await sync_derived_connections(db, tid)
