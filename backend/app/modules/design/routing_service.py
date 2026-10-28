# ============================================================
# OPSYN DESIGN ROUTING SERVICE — app/modules/design/routing_service.py
#
# POST /designs/{id}/route: the road-graph route between two points of a
# design, computed by the FTTx engine's CableRouter (Dijkstra over the
# design's noded road inputs, device points tied in as exact vertices,
# short stubs from the road to each device). This is the ONE way a cable
# gets a ROAD_GRAPH geometry — auto design (Phase 5) and manual cable
# drawing (Phase 6) both call it (plan §2 invariant 4).
#
# Ends are given as an asset of the design / live network, or a point.
# No route → 422 with the reason; never a straight-line fallback.
# ============================================================

from __future__ import annotations

import uuid
from typing import Any

import pyproj
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.design.engine_bridge import ENGINE_LOCK, MissingInputs, context_for

_GEOD = pyproj.Geod(ellps="WGS84")


async def _resolve_end(db: AsyncSession, tid: uuid.UUID, design_id: uuid.UUID, end: dict[str, Any], label: str) -> tuple[float, float, str | None]:
    if end.get("asset_id"):
        try:
            aid = uuid.UUID(str(end["asset_id"]))
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"The {label} asset id is not valid")
        r = (await db.execute(text("""
            SELECT asset_code, ST_X(ST_PointOnSurface(geom)) AS lng, ST_Y(ST_PointOnSurface(geom)) AS lat
            FROM net_assets WHERE id = :id AND tenant_id = :tid AND deleted_at IS NULL
              AND (design_id = :d OR design_id IS NULL)
        """), {"id": aid, "tid": tid, "d": design_id})).first()
        if r is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"The {label} asset is not in this design or the live network")
        return float(r.lng), float(r.lat), r.asset_code
    try:
        lng, lat = float(end["lng"]), float(end["lat"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Give the {label} as an asset_id or as lng and lat")
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"The {label} point is out of range")
    return lng, lat, None


async def route(db: AsyncSession, tid: uuid.UUID, design: Any, start: dict[str, Any], end: dict[str, Any]) -> dict[str, Any]:
    from fastapi.concurrency import run_in_threadpool

    a_lng, a_lat, a_code = await _resolve_end(db, tid, design.id, start, "start")
    b_lng, b_lat, b_code = await _resolve_end(db, tid, design.id, end, "end")
    try:
        ctx = await context_for(db, tid, design)
    except MissingInputs as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

    def _run():
        with ENGINE_LOCK:
            geom, _len = ctx.router.find_shortest_path_points(ctx.to_utm(a_lng, a_lat), ctx.to_utm(b_lng, b_lat))
        if geom is None or geom.isEmpty():
            return None
        return [ctx.to_wgs(p.x(), p.y()) for p in geom.asPolyline()]

    coords = await run_in_threadpool(_run)
    if not coords or len(coords) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"No road route joins {a_code or 'the start'} and {b_code or 'the end'}. "
                            "Check that the design's roads connect between them.")
    lons, lats = zip(*coords)
    length = abs(_GEOD.line_length(lons, lats))
    straight = abs(_GEOD.line_length([a_lng, b_lng], [a_lat, b_lat]))
    return {
        "geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]},
        "length_m": round(length, 1), "straight_line_m": round(straight, 1),
        "route_method": "ROAD_GRAPH", "from_code": a_code, "to_code": b_code,
    }
