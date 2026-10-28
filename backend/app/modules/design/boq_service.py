# ============================================================
# OPSYN DESIGN BOQ SERVICE — app/modules/design/boq_service.py
#
# The bill of quantities for whatever is in a design's working set — the
# same for auto- and hand-made designs (decision D2). Two parts:
#
#   quantities   straight from the database: devices by type (poles split
#                new / existing), cables by category and fibre count with
#                total length (length_m is computed from the geometry by
#                the database, never by a client)
#   streets      the FTTx engine's own populate_boq_layer, run on the
#                hydrated design (hydrator.py) over the design's road and
#                homepass inputs: per-street homepasses, FDT/FAT/pole/
#                closure counts, drop-length classes (10/50/100/150 m),
#                feeder and closure-to-FDT cable, aerial accessories. Needs
#                roads; without them the result says so instead of guessing.
#
# Unit rates / prices are not modelled in OpSyn yet; the BOQ is quantities.
# ============================================================

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.design.engine_bridge import (
    ENGINE_LOCK, HOMEPASS_COUNT_FIELD, EngineContext, MissingInputs, context_for, load_inputs,
)
from app.modules.design.hydrator import hydrate, load_working_set
from app.modules.network.asset_types import ASSET_TYPES, CABLE_CATEGORIES

QUANTITIES_SQL = """
SELECT 'asset' AS kind, asset_type AS key,
       CASE WHEN asset_type = 'POLE' AND coalesce((attributes->>'existing')::boolean, false) THEN 'existing' ELSE '' END AS variant,
       count(*) AS n, NULL::float8 AS length_m, NULL::int AS fiber_count
FROM net_assets WHERE design_id = :d AND tenant_id = :tid AND deleted_at IS NULL
GROUP BY 1, 2, 3
UNION ALL
SELECT 'cable', cable_category, '', count(*), sum(length_m)::float8, fiber_count
FROM net_cables WHERE design_id = :d AND tenant_id = :tid AND deleted_at IS NULL
GROUP BY 2, fiber_count
"""


async def quantities(db: AsyncSession, tid: uuid.UUID, design_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (await db.execute(text(QUANTITIES_SQL), {"d": design_id, "tid": tid})).all()
    out: list[dict[str, Any]] = []
    for r in rows:
        if r.kind == "asset":
            label = ASSET_TYPES[r.key].label + (" (existing)" if r.variant == "existing" else " (new)" if r.key == "POLE" else "")
            out.append({"group": "Devices", "item": label, "code": r.key, "quantity": int(r.n), "unit": "each"})
        else:
            fibres = f", {r.fiber_count} fibres" if r.fiber_count else ""
            out.append({"group": "Cable", "item": f"{CABLE_CATEGORIES[r.key].label} cable{fibres}", "code": r.key,
                        "quantity": round((r.length_m or 0.0), 1), "unit": "m", "pieces": int(r.n),
                        "fiber_count": r.fiber_count})
    order = {"Devices": 0, "Cable": 1}
    out.sort(key=lambda x: (order[x["group"]], x["item"]))
    return out


def _street_boq(ctx: EngineContext, hydrated: Any) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Run the engine's populate_boq_layer. Engine globals are set under the lock and restored."""
    from app.modules.fttx_designer.engine import runtime_config as rc
    from app.modules.fttx_designer.engine.boq import populate_boq_layer
    from app.modules.fttx_designer.engine.geometry_compat import QgsVectorLayer
    from app.modules.fttx_designer.engine.perf_logger import PerformanceLogger
    from app.modules.fttx_designer.engine.pipeline import _OUTPUT_LAYER_SCHEMAS
    from app.modules.fttx_designer.geojson_io import layer_to_rows

    cfg = ctx.config
    empty = lambda name, fields: QgsVectorLayer.from_records([], field_names=fields, crs=ctx.crs, layer_id=name)
    homepass_layer = ctx.layers.get("homepass") or empty("homepass", [HOMEPASS_COUNT_FIELD])
    pole_layer = ctx.layers.get("pole") or empty("pole", [])
    boq_layer = QgsVectorLayer.from_records([], field_names=_OUTPUT_LAYER_SCHEMAS["boq"], layer_id="boq")

    with ENGINE_LOCK:
        saved = (rc.HOMEPASS_FIELD_NAME, rc.MAX_BOX_TO_CUSTOMER_DISTANCE, rc.MAX_BOX_TO_BOX_DISTANCE,
                 rc.DROP_LENGTH_TOLERANCE)
        rc.HOMEPASS_FIELD_NAME = HOMEPASS_COUNT_FIELD
        rc.MAX_BOX_TO_CUSTOMER_DISTANCE = cfg.max_box_to_customer_distance
        rc.MAX_BOX_TO_BOX_DISTANCE = cfg.max_box_to_box_distance
        rc.DROP_LENGTH_TOLERANCE = cfg.drop_length_tolerance
        try:
            logger = PerformanceLogger()
            populate_boq_layer(
                boq_layer, ctx.layers["road"], homepass_layer, pole_layer,
                hydrated.homepasses, hydrated.fdts, hydrated.fats, hydrated.b2b_cables,
                hydrated.closures, hydrated.closure_cables, hydrated.pickup_cables,
                coverage_pct=cfg.coverage_pct, cascade_architecture=cfg.cascade_architecture, logger=logger,
            )
            findings = logger.get_findings()
        finally:
            (rc.HOMEPASS_FIELD_NAME, rc.MAX_BOX_TO_CUSTOMER_DISTANCE, rc.MAX_BOX_TO_BOX_DISTANCE,
             rc.DROP_LENGTH_TOLERANCE) = saved
    return layer_to_rows(boq_layer), findings


async def compute_boq(db: AsyncSession, tid: uuid.UUID, design: Any) -> dict[str, Any]:
    from fastapi.concurrency import run_in_threadpool

    result: dict[str, Any] = {
        "quantities": await quantities(db, tid, design.id),
        "streets": [], "street_boq_available": False, "notes": [], "engine_findings": [],
    }
    try:
        ctx = await context_for(db, tid, design)
    except MissingInputs as exc:
        result["notes"].append(str(exc))
        return result
    ws = await load_working_set(db, tid, design.id)
    homepass_fc = (await load_inputs(db, tid, design.id, ("homepass",))).get("homepass")
    hydrated = hydrate(ctx, ws, homepass_fc)
    rows, findings = await run_in_threadpool(_street_boq, ctx, hydrated)
    result["streets"] = rows
    result["street_boq_available"] = True
    result["engine_findings"] = findings
    if not homepass_fc:
        result["notes"].append("No homepasses uploaded: the street BOQ counts no customers.")
    return result
