# ============================================================
# OPSYN NETWORK TOPOLOGY SERVICE — app/modules/network/topology_service.py
#
# Connections, trace, utilisation and fibres for the live network
# (design_id IS NULL). SQL lives in topology.py; this module adds the
# rules: tenant checks on every id, no self or cyclic links, derived
# connections can only change through the data they come from, every
# write audited ("net_connection" / "net_fiber").
# ============================================================

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.infrastructure.audit_service import write_audit_entry
from app.modules.network.asset_types import ASSET_TYPES, CUSTOMER_TYPES, ROOT_TYPES
from app.modules.network.models import NetConnection, NetFiber
from app.modules.network.schemas import (
    AssetConnections, AssetRef, CableRef, ConnectionCreate, ConnectionOut, FibreOut,
    TraceAsset, TraceHop, TraceOut, UtilisationOut,
)
from app.modules.network.service import _uuid_or_404, _uuid_or_422
from app.modules.network.topology import (
    CABLE_GEOMETRY_SQL, MAX_DEPTH, MAX_TRACE_ROWS, UTIL_BASIS, UTIL_CAPACITY, UTIL_JOINS, UTIL_USED,
    fibres_for, shallowest, trace_sql, util_state,
)

_DERIVED_LABEL = {
    "net_cables": "the cable's endpoints",
    "attr:parent_splitter": "the splitter's parent splitter",
    "attr:cabinet": "the splitter's cabinet",
    "attr:parent_fdt": "the FAT's parent FDT code",
}


async def _live_asset(db: AsyncSession, tid: uuid.UUID, asset_id: uuid.UUID, what: str = "Asset") -> Any:
    row = (await db.execute(text("""
        SELECT id, asset_code, asset_type, name FROM net_assets
        WHERE id = :id AND tenant_id = :tid AND deleted_at IS NULL AND design_id IS NULL
    """), {"id": asset_id, "tid": tid})).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")
    return row


# ── Connections ──────────────────────────────────────────────

_CONN_SQL = """
SELECT c.id, c.connection_type, c.lifecycle_status, c.source_table,
       p.id AS p_id, p.asset_code AS p_code, p.asset_type AS p_type, p.name AS p_name,
       cb.id AS cb_id, cb.asset_code AS cb_code, cb.cable_category AS cb_cat, cb.length_m::float8 AS cb_len
FROM net_connections c
JOIN net_assets p ON p.id = c.{peer} AND p.deleted_at IS NULL
LEFT JOIN net_cables cb ON cb.id = c.via_cable_id AND cb.deleted_at IS NULL
WHERE c.{self} = :id AND c.tenant_id = :tid AND c.deleted_at IS NULL AND c.design_id IS NULL
ORDER BY p.asset_code
"""


def _conn_out(r: Any) -> ConnectionOut:
    return ConnectionOut(
        id=str(r.id), connection_type=r.connection_type, lifecycle_status=r.lifecycle_status,
        derived_from=r.source_table,
        peer=AssetRef(id=str(r.p_id), asset_code=r.p_code, asset_type=r.p_type, name=r.p_name),
        via_cable=CableRef(id=str(r.cb_id), asset_code=r.cb_code, cable_category=r.cb_cat, length_m=r.cb_len)
        if r.cb_id else None,
    )


async def list_connections(db: AsyncSession, tid: uuid.UUID, asset_id: str) -> AssetConnections:
    aid = _uuid_or_404(asset_id)
    await _live_asset(db, tid, aid)
    params = {"id": aid, "tid": tid}
    up = (await db.execute(text(_CONN_SQL.format(peer="source_asset_id", self="dest_asset_id")), params)).all()
    down = (await db.execute(text(_CONN_SQL.format(peer="dest_asset_id", self="source_asset_id")), params)).all()
    return AssetConnections(upstream=[_conn_out(r) for r in up], downstream=[_conn_out(r) for r in down])


async def create_connection(db: AsyncSession, tid: uuid.UUID, caller: Any, body: ConnectionCreate) -> ConnectionOut:
    src = _uuid_or_422(body.source_asset_id, "source_asset_id")
    dst = _uuid_or_422(body.dest_asset_id, "dest_asset_id")
    if src == dst:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "An asset cannot feed itself")
    s = await _live_asset(db, tid, src, "Source asset")
    d = await _live_asset(db, tid, dst, "Destination asset")
    cable = _uuid_or_422(body.via_cable_id, "via_cable_id")
    if cable is not None:
        ok = (await db.execute(text("""
            SELECT 1 FROM net_cables WHERE id = :id AND tenant_id = :tid AND deleted_at IS NULL AND design_id IS NULL
        """), {"id": cable, "tid": tid})).first()
        if ok is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That cable is not in the live network")
    # A loop would make tracing meaningless: dest must not already feed source
    loop = (await db.execute(text(trace_sql("downstream")), {
        "id": dst, "tid": tid, "max_depth": MAX_DEPTH, "cap": MAX_TRACE_ROWS,
    })).all()
    if any(r.asset_id == src for r in loop):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"{d.asset_code} already feeds {s.asset_code}; this link would create a loop")

    conn = NetConnection(tenant_id=tid, source_asset_id=src, dest_asset_id=dst, via_cable_id=cable,
                         connection_type=body.connection_type, lifecycle_status="ACTIVE", created_by=caller.id)
    try:
        # A savepoint: a rejected link undoes only itself, not the caller's other work
        async with db.begin_nested():
            db.add(conn)
            await db.flush()
    except IntegrityError as exc:
        if "uq_net_connections_manual_pair" in str(exc.orig):
            raise HTTPException(status.HTTP_409_CONFLICT, f"{s.asset_code} already feeds {d.asset_code}")
        raise
    await write_audit_entry(
        db, asset_type="net_connection", asset_id=conn.id, asset_key=f"{s.asset_code} → {d.asset_code}",
        action="create", actor_user=caller, tenant_id=tid,
        new_data={"source": s.asset_code, "dest": d.asset_code, "type": body.connection_type,
                  "via_cable_id": str(cable) if cable else None},
    )
    row = (await db.execute(text(_CONN_SQL.format(peer="dest_asset_id", self="source_asset_id")),
                            {"id": src, "tid": tid})).all()
    return _conn_out(next(r for r in row if r.id == conn.id))


async def delete_connection(db: AsyncSession, tid: uuid.UUID, caller: Any, connection_id: str) -> None:
    cid = _uuid_or_404(connection_id, "Connection")
    conn = await db.get(NetConnection, cid)
    if conn is None or conn.tenant_id != tid or conn.deleted_at is not None or conn.design_id is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    if conn.source_table:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"This connection comes from {_DERIVED_LABEL.get(conn.source_table, conn.source_table)}; "
                            "change that instead and the connection follows")
    from datetime import datetime, timezone
    conn.deleted_at = datetime.now(timezone.utc)
    conn.deleted_by = caller.id
    await db.flush()
    await write_audit_entry(
        db, asset_type="net_connection", asset_id=conn.id, asset_key=None, action="soft_delete",
        actor_user=caller, tenant_id=tid,
        old_data={"source_asset_id": str(conn.source_asset_id), "dest_asset_id": str(conn.dest_asset_id),
                  "type": conn.connection_type},
    )


# ── Trace ────────────────────────────────────────────────────

def _trace_asset(r: Any) -> TraceAsset:
    return TraceAsset(id=str(r.asset_id), asset_code=r.asset_code, asset_type=r.asset_type, name=r.name,
                      lifecycle_status=r.lifecycle_status, lng=float(r.lng), lat=float(r.lat))


async def trace(db: AsyncSession, tid: uuid.UUID, asset_id: str, direction: str) -> TraceOut:
    aid = _uuid_or_404(asset_id)
    await _live_asset(db, tid, aid)
    raw = (await db.execute(text(trace_sql(direction)), {
        "id": aid, "tid": tid, "max_depth": MAX_DEPTH, "cap": MAX_TRACE_ROWS + 1,
    })).all()
    truncated = len(raw) > MAX_TRACE_ROWS
    rows = shallowest(raw[:MAX_TRACE_ROWS])
    by_id = {r.asset_id: r for r in rows}

    hops = [TraceHop(
        asset=_trace_asset(r), depth=r.depth,
        from_id=str(r.from_id) if r.from_id else None, connection_type=r.connection_type,
        via_cable=CableRef(id=str(r.via_cable_id), asset_code=r.cable_code, cable_category=r.cable_category,
                           length_m=r.cable_length_m) if r.via_cable_id and r.cable_code else None,
    ) for r in rows]

    path_ids: list[str] = []
    root = None
    path_length: float | None = None
    if direction == "upstream" and rows:
        # Prefer the nearest OLT/POP/SITE; otherwise the furthest asset reached
        roots = [r for r in rows if r.asset_type in ROOT_TYPES and r.depth > 0]
        end = roots[0] if roots else max(rows, key=lambda r: r.depth)
        chain = []
        node = end
        while node is not None:
            chain.append(node)
            node = by_id.get(node.from_id) if node.from_id else None
        chain.reverse()                                     # start → root
        path_ids = [str(r.asset_id) for r in chain]
        root = _trace_asset(end) if end.depth > 0 else None
        lengths = [r.cable_length_m for r in chain if r.via_cable_id]
        path_length = round(sum(x for x in lengths if x is not None), 1) if lengths else None
        reached_root = bool(roots)
    else:
        reached_root = False

    reached = [r for r in rows if r.depth > 0]
    counts: dict[str, int] = {}
    for r in reached:
        counts[r.asset_type] = counts.get(r.asset_type, 0) + 1
    customers = sum(counts.get(t, 0) for t in CUSTOMER_TYPES)

    # Geometry for the map highlight: points, cables, and logical links
    on_path = set(path_ids)
    features: list[dict[str, Any]] = []
    for r in rows:
        role = "start" if r.depth == 0 else ("root" if root and str(r.asset_id) == root.id else
                                            "path" if str(r.asset_id) in on_path else "branch")
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(r.lng), float(r.lat)]},
                         "properties": {"kind": "asset", "id": str(r.asset_id), "asset_code": r.asset_code,
                                        "asset_type": r.asset_type, "role": role}})
    cable_ids = sorted({r.via_cable_id for r in rows if r.via_cable_id})
    if cable_ids:
        for c in (await db.execute(text(CABLE_GEOMETRY_SQL), {"ids": cable_ids, "tid": tid})).all():
            features.append({"type": "Feature", "geometry": json.loads(c.geojson),
                             "properties": {"kind": "cable", "id": c.id, "asset_code": c.asset_code,
                                            "cable_category": c.cable_category, "logical": False}})
    for r in rows:
        if r.depth > 0 and not r.via_cable_id and r.from_id in by_id:
            f = by_id[r.from_id]
            features.append({"type": "Feature",
                             "geometry": {"type": "LineString", "coordinates": [[float(f.lng), float(f.lat)],
                                                                                [float(r.lng), float(r.lat)]]},
                             "properties": {"kind": "link", "connection_type": r.connection_type, "logical": True}})

    return TraceOut(
        direction=direction, start_id=str(aid), hops=hops, path_ids=path_ids, root=root,
        reached_root=reached_root, path_length_m=path_length, counts_by_type=counts,
        customers=customers, truncated=truncated,
        geometry={"type": "FeatureCollection", "features": features},
    )


# ── Utilisation ──────────────────────────────────────────────

async def utilisation(db: AsyncSession, tid: uuid.UUID, asset_id: str) -> UtilisationOut:
    aid = _uuid_or_404(asset_id)
    r = (await db.execute(text(f"""
        SELECT a.asset_type, {UTIL_CAPACITY} AS capacity, {UTIL_USED} AS used, {UTIL_BASIS} AS basis
        FROM net_assets a {UTIL_JOINS}
        WHERE a.id = :id AND a.tenant_id = :tid AND a.deleted_at IS NULL AND a.design_id IS NULL
    """), {"id": aid, "tid": tid})).first()
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    capacity = int(r.capacity) if r.capacity is not None else None
    used = int(r.used) if r.used is not None else None
    pct, state = util_state(capacity, used)
    return UtilisationOut(
        capacity=capacity, used=used, pct=pct, state=state, basis=r.basis,
        available=(capacity - used) if capacity is not None and used is not None else None,
        capacity_label=ASSET_TYPES[r.asset_type].capacity_label,
    )


# ── Fibres ───────────────────────────────────────────────────

async def _live_cable(db: AsyncSession, tid: uuid.UUID, cable_id: str) -> Any:
    cid = _uuid_or_404(cable_id, "Cable")
    row = (await db.execute(text("""
        SELECT id, asset_code, fiber_count FROM net_cables
        WHERE id = :id AND tenant_id = :tid AND deleted_at IS NULL AND design_id IS NULL
    """), {"id": cid, "tid": tid})).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cable not found")
    return row


async def list_fibres(db: AsyncSession, tid: uuid.UUID, cable_id: str) -> list[FibreOut]:
    cable = await _live_cable(db, tid, cable_id)
    stored = {r.fiber_no: {"status": r.status} for r in (await db.execute(text(
        "SELECT fiber_no, status FROM net_fibers WHERE cable_id = :id"), {"id": cable.id})).all()}
    return [FibreOut(**f) for f in fibres_for(cable.fiber_count, stored)]


async def set_fibre_status(db: AsyncSession, tid: uuid.UUID, caller: Any, cable_id: str,
                           fiber_no: int, new_status: str) -> FibreOut:
    cable = await _live_cable(db, tid, cable_id)
    if not cable.fiber_count or not 1 <= fiber_no <= cable.fiber_count:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{cable.asset_code} has no fibre {fiber_no}" if cable.fiber_count
                            else f"{cable.asset_code} has no fibre count recorded")
    fibre = (await db.execute(text("SELECT id, status FROM net_fibers WHERE cable_id = :c AND fiber_no = :n"),
                              {"c": cable.id, "n": fiber_no})).first()
    before = fibre.status if fibre else "FREE"
    if fibre is None:
        db.add(NetFiber(tenant_id=tid, cable_id=cable.id, fiber_no=fiber_no, status=new_status))
    else:
        await db.execute(text("UPDATE net_fibers SET status = :s, updated_at = now() WHERE id = :id"),
                         {"s": new_status, "id": fibre.id})
    await db.flush()
    await write_audit_entry(
        db, asset_type="net_fiber", asset_id=cable.id, asset_key=f"{cable.asset_code} fibre {fiber_no}",
        action="update", actor_user=caller, tenant_id=tid,
        old_data={"status": before}, new_data={"status": new_status},
    )
    return next(f for f in await list_fibres(db, tid, cable_id) if f.fiber_no == fiber_no)
