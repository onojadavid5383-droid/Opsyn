# ============================================================
# OPSYN DESIGN SNAP — app/modules/design/snap.py
# Network GIS Phase 6: where a click in the manual design tools lands.
# POST /designs/{id}/snap {lng, lat, radius_m?, targets?} → the best
# candidate within the radius, by kind first, then distance:
#
#   asset        a device of this design (not a splitter inside a FAT)
#   pole_input   an uploaded pole / existing structure (mount a FAT on it)
#   homepass     an uploaded homepass (the far end of a drop)
#   pickup       an uploaded pickup point (the start of a feeder)
#   live_asset   a device already in service (tap into the live network)
#   vertex       a vertex of one of the design's cables
#   road         the nearest point on a design road, moved ROAD_SIDE_M
#                towards the click (devices sit beside the road, not on it)
#   boundary     the design boundary's edge
# Nothing within reach → the click itself (snapped: false).
# ============================================================

from __future__ import annotations

import math
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

KINDS = ("asset", "pole_input", "homepass", "pickup", "live_asset", "vertex", "road", "boundary")
ROAD_SIDE_M = 3.0
# Roads are caught within the same radius as points: a click in the middle of a
# block must not pull a device onto a street 50 m away (seen in Phase 7 testing)
ROAD_REACH_FACTOR = 1.0
MAX_RADIUS_M = 200.0


def side_of_road(road: tuple[float, float], click: tuple[float, float], offset_m: float = ROAD_SIDE_M) -> tuple[float, float]:
    """A point offset_m from the road point towards the click (or the click, if closer)."""
    lat0 = math.radians(road[1])
    dx = math.radians(click[0] - road[0]) * math.cos(lat0) * 6_371_000
    dy = math.radians(click[1] - road[1]) * 6_371_000
    dist = math.hypot(dx, dy)
    if dist < 0.5:
        return road
    k = min(dist, offset_m) / dist
    return (road[0] + math.degrees(dx * k / (6_371_000 * math.cos(lat0))),
            road[1] + math.degrees(dy * k / 6_371_000))


async def snap(db: AsyncSession, tid: uuid.UUID, design: Any, lng: float, lat: float,
               radius_m: float = 15.0, targets: list[str] | None = None) -> dict[str, Any]:
    radius = max(1.0, min(float(radius_m), MAX_RADIUS_M))
    kinds = [k for k in (targets or KINDS) if k in KINDS]
    p = {"d": design.id, "tid": tid, "lng": lng, "lat": lat, "r": radius, "rr": radius * ROAD_REACH_FACTOR}
    pt = "ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)"
    parts = {
        "asset": f"""SELECT 'asset' AS kind, a.id::text AS id, a.asset_code AS code, a.asset_type AS sub,
                        ST_X(a.geom) AS x, ST_Y(a.geom) AS y, ST_Distance(a.geom::geography, {pt}::geography) AS m
                     FROM net_assets a WHERE a.design_id = :d AND a.tenant_id = :tid AND a.deleted_at IS NULL
                       AND a.parent_id IS NULL AND ST_DWithin(a.geom::geography, {pt}::geography, :r)""",
        "pole_input": f"""SELECT 'pole_input', i.id::text, coalesce(i.properties->>'Name', i.properties->>'name', 'Pole'), i.layer_key,
                        ST_X(i.geom), ST_Y(i.geom), ST_Distance(i.geom::geography, {pt}::geography)
                     FROM design_inputs i WHERE i.design_id = :d AND i.layer_key IN ('pole', 'existing_structure')
                       AND ST_DWithin(i.geom::geography, {pt}::geography, :r)""",
        "homepass": f"""SELECT 'homepass', i.id::text, 'Homepass', coalesce(i.properties->>'customers', '1'),
                        ST_X(i.geom), ST_Y(i.geom), ST_Distance(i.geom::geography, {pt}::geography)
                     FROM design_inputs i WHERE i.design_id = :d AND i.layer_key = 'homepass'
                       AND ST_DWithin(i.geom::geography, {pt}::geography, :r)""",
        "pickup": f"""SELECT 'pickup', i.id::text, coalesce(i.properties->>'name', 'Pickup point'), 'pickup',
                        ST_X(i.geom), ST_Y(i.geom), ST_Distance(i.geom::geography, {pt}::geography)
                     FROM design_inputs i WHERE i.design_id = :d AND i.layer_key = 'pickup'
                       AND ST_DWithin(i.geom::geography, {pt}::geography, :r)""",
        "live_asset": f"""SELECT 'live_asset', a.id::text, a.asset_code, a.asset_type,
                        ST_X(ST_PointOnSurface(a.geom)), ST_Y(ST_PointOnSurface(a.geom)), ST_Distance(a.geom::geography, {pt}::geography)
                     FROM net_assets a WHERE a.design_id IS NULL AND a.tenant_id = :tid AND a.deleted_at IS NULL
                       AND ST_DWithin(a.geom::geography, {pt}::geography, :r)""",
        "vertex": f"""SELECT 'vertex', c.id::text, c.asset_code, c.cable_category,
                        ST_X(dp.geom), ST_Y(dp.geom), ST_Distance(dp.geom::geography, {pt}::geography)
                     FROM net_cables c, LATERAL ST_DumpPoints(c.geom) dp
                     WHERE c.design_id = :d AND c.tenant_id = :tid AND c.deleted_at IS NULL
                       AND ST_DWithin(c.geom::geography, {pt}::geography, :r)
                       AND ST_DWithin(dp.geom::geography, {pt}::geography, :r)""",
        "road": f"""SELECT 'road', i.id::text, coalesce(i.properties->>'name', 'Road'), 'road',
                        ST_X(ST_ClosestPoint(i.geom, {pt})), ST_Y(ST_ClosestPoint(i.geom, {pt})),
                        ST_Distance(i.geom::geography, {pt}::geography)
                     FROM design_inputs i WHERE i.design_id = :d AND i.layer_key = 'road'
                       AND ST_DWithin(i.geom::geography, {pt}::geography, :rr)""",
        "boundary": f"""SELECT 'boundary', d.id::text, 'Boundary', 'boundary',
                        ST_X(ST_ClosestPoint(ST_Boundary(d.boundary), {pt})), ST_Y(ST_ClosestPoint(ST_Boundary(d.boundary), {pt})),
                        ST_Distance(ST_Boundary(d.boundary)::geography, {pt}::geography)
                     FROM designs d WHERE d.id = :d AND d.boundary IS NOT NULL
                       AND ST_DWithin(ST_Boundary(d.boundary)::geography, {pt}::geography, :r)""",
    }
    if not kinds:
        return {"snapped": False, "lng": lng, "lat": lat, "kind": None, "candidates": []}
    # Each part names its columns: a UNION takes its names from whichever part comes first
    sql = " UNION ALL ".join(f"SELECT * FROM ({parts[k]}) AS q_{k}(kind, id, code, sub, x, y, m)" for k in kinds)
    rows = (await db.execute(text(sql), p)).all()
    order = {k: i for i, k in enumerate(kinds)}
    rows = sorted(rows, key=lambda r: (order[r.kind], r.m))
    cands = []
    for r in rows[:8]:
        x, y = float(r.x), float(r.y)
        if r.kind == "road":
            x, y = side_of_road((x, y), (lng, lat))
        cands.append({"kind": r.kind, "id": r.id, "code": r.code, "sub": r.sub, "lng": x, "lat": y,
                      "distance_m": round(float(r.m), 1)})
    if not cands:
        return {"snapped": False, "lng": lng, "lat": lat, "kind": None, "candidates": []}
    return {"snapped": True, **cands[0], "candidates": cands}
