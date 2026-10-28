# ============================================================
# OPSYN DESIGN RECALC — app/modules/design/recalc.py
# Network GIS Phase 7: hybrid local recalculation (decision D7).
#
# After an edit, only what it affects is recomputed — never a re-cluster:
#   reroute()   the cables of moved devices:
#                 ROAD_GRAPH  routed again along the design's roads (the
#                             engine's CableRouter, via routing_service)
#                             between the devices they join
#                 DIRECT      a drop: straight again from its FAT to the
#                             same customer point (a customer out of reach
#                             shows up as DROP_TOO_LONG, not re-assigned)
#                 by hand     hand-drawn / as-built lines keep their shape;
#                             only the moved end follows
#               lengths come from the geometry (net_cables trigger)
#   deltas      what the edit changed: the BOQ quantities (before → after,
#               per line), the validation issues (new / resolved) and the
#               features to redraw — so the client patches its cache
#               instead of reloading the design
# Re-clustering (FATs re-assigned, FDTs re-placed) stays with a full engine
# run: "Regenerate" = auto design (Phase 5), a new version.
# ============================================================

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.design import boq_service, validation_service


async def reroute(db: AsyncSession, design: Any, tr: Any, asset_ids: list[uuid.UUID]) -> list[dict[str, Any]]:
    """Recompute the lines of every cable attached to these devices. → one entry per cable."""
    from app.modules.design.operations import _dedupe, _road_line   # shared with the operations

    cables = (await db.execute(text("""
        SELECT c.id, c.asset_code, c.cable_category, c.route_method, c.length_m::float8 AS before_m,
               ST_AsGeoJSON(c.geom, 9) AS g,
               ST_X(s.geom) AS sx, ST_Y(s.geom) AS sy, ST_X(t.geom) AS tx, ST_Y(t.geom) AS ty
        FROM net_cables c
        LEFT JOIN net_assets s ON s.id = c.source_asset_id
        LEFT JOIN net_assets t ON t.id = c.dest_asset_id
        WHERE c.design_id = :d AND c.deleted_at IS NULL
          AND (c.source_asset_id = ANY(:ids) OR c.dest_asset_id = ANY(:ids))
        ORDER BY c.asset_code
    """), {"d": design.id, "ids": list(asset_ids)})).all()
    await tr.touch("net_cables", [c.id for c in cables])
    out: list[dict[str, Any]] = []
    for c in cables:
        coords = json.loads(c.g)["coordinates"]
        a = [c.sx, c.sy] if c.sx is not None else coords[0]
        b = [c.tx, c.ty] if c.tx is not None else coords[-1]
        how, note = c.route_method, None
        if c.route_method == "ROAD_GRAPH":
            try:
                line = await _road_line(db, design, (a[0], a[1]), (b[0], b[1]))
            except HTTPException:
                # No road joins the new spot: keep the line, move its ends, say so
                line, how, note = [a, *coords[1:-1], b], "MANUAL_GEOMETRY", "no road route from the new spot; ends moved, marked hand-drawn"
        elif c.route_method == "DIRECT":
            line = [a, b]
        else:
            line = [a, *coords[1:-1], b]
        line = _dedupe(line)
        await db.execute(text("""
            UPDATE net_cables SET geom = ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326), route_method = :m, updated_at = now()
            WHERE id = :id
        """), {"g": json.dumps({"type": "LineString", "coordinates": line}), "m": how, "id": c.id})
        after = (await db.execute(text("SELECT length_m::float8 FROM net_cables WHERE id = :id"), {"id": c.id})).scalar_one()
        out.append({"id": str(c.id), "code": c.asset_code, "category": c.cable_category, "route_method": how,
                    "before_m": round(c.before_m or 0.0, 1), "after_m": round(after or 0.0, 1),
                    **({"note": note} if note else {})})
    return out


# ── Deltas ───────────────────────────────────────────────────

def _qkey(q: dict[str, Any]) -> str:
    return f"{q['group']}|{q['item']}"


async def snapshot(db: AsyncSession, tid: uuid.UUID, design_id: uuid.UUID) -> dict[str, Any]:
    """What deltas compare: BOQ quantities and the stored issues."""
    return {
        "boq": {_qkey(q): q for q in await boq_service.quantities(db, tid, design_id)},
        "issues": {(i["code"], i["asset_id"], i["cable_id"]): i
                   for i in await validation_service.stored_issues(db, tid, design_id)},
    }


def boq_delta(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for key in sorted(set(before) | set(after)):
        b, a = before.get(key), after.get(key)
        qb, qa = (b or {}).get("quantity", 0), (a or {}).get("quantity", 0)
        if round(qb, 1) == round(qa, 1):
            continue
        ref = a or b
        out.append({"item": ref["item"], "code": ref["code"], "unit": ref["unit"], "group": ref["group"],
                    "before": qb, "after": qa, "change": round(qa - qb, 1)})
    return out


def validation_delta(before: dict[Any, Any], after: dict[Any, Any]) -> dict[str, list[dict[str, Any]]]:
    brief = lambda i: {"severity": i["severity"], "code": i["code"], "message": i["message"]}   # noqa: E731
    return {"new": [brief(after[k]) for k in after if k not in before],
            "resolved": [brief(before[k]) for k in before if k not in after]}


async def changed_features(db: AsyncSession, tid: uuid.UUID, design: Any, patch: dict[str, Any]) -> dict[str, Any]:
    """The rows a patch created or updated, as map features, and the ids it removed."""
    from app.modules.design.service import working_set_features

    def ids(kind: str, table: str) -> list[uuid.UUID]:
        return [uuid.UUID(str(r["id"])) for r in patch[kind].get(table) or []]

    assets = ids("restore", "net_assets") + ids("update", "net_assets")
    cables = ids("restore", "net_cables") + ids("update", "net_cables")
    feats = await working_set_features(db, tid, design, asset_ids=assets, cable_ids=cables)
    return {"features": feats["features"],
            "removed": {"assets": list(patch["delete"].get("net_assets") or []),
                        "cables": list(patch["delete"].get("net_cables") or [])}}
