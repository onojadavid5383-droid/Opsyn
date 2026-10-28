# ============================================================
# OPSYN — tests/integration/test_recalc_db.py
# Network GIS Phase 7 against real PostGIS and the real engine: the plan's
# "move FAT-0014" acceptance — moving a FAT re-routes its box-to-box cables
# along the roads and redraws its drops, and the answer carries the new
# geometry, lengths, BOQ changes and validation changes — for a FAT drawn
# by hand AND a FAT placed by the engine. Undo puts everything back and
# reports the issues it resolves. recalc=false only moves the ends.
# Harness as the other DB tests: NETWORK_GIS_DB_URL, rolled back at the end.
# ============================================================

import json
import os
import types
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

if os.environ.get("NETWORK_GIS_DB_URL"):
    import main  # noqa: F401 — registers every ORM mapper

from app.modules.design import auto_design, operations, service
from app.modules.design.inputs import parse_input_file
from app.modules.design.schemas import DesignCreate
from app.modules.fttx_designer.config_io import config_from_dict
from app.modules.fttx_designer.engine.pipeline import run_fttx_design
from app.modules.fttx_designer.geojson_io import build_input_layers, layer_to_geojson, layer_to_rows
from app.modules.fttx_designer.models import FttxDesignRun, FttxDesignRunLayer, FttxDesignRunOutput

DB_URL = os.environ.get("NETWORK_GIS_DB_URL")
pytestmark = [
    pytest.mark.skipif(not DB_URL, reason="NETWORK_GIS_DB_URL not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
CALLER = types.SimpleNamespace(id=uuid.UUID("00000000-0000-0000-0000-000000000002"), username="t", staff_profile=None)
X0, Y0, D = 3.4100, 6.6500, 0.001


def fc(features):
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


ROADS = fc([
    *({"type": "Feature", "properties": {"name": f"Recalc Street {i}"},
       "geometry": {"type": "LineString", "coordinates": [[X0, Y0 + i * D], [X0 + 3 * D, Y0 + i * D]]}} for i in range(4)),
    *({"type": "Feature", "properties": {"name": f"Recalc Avenue {i}"},
       "geometry": {"type": "LineString", "coordinates": [[X0 + i * D, Y0], [X0 + i * D, Y0 + 3 * D]]}} for i in range(4)),
])
HP = [{"type": "Feature", "properties": {"Customers": 2 if k % 5 == 0 else 1},
       "geometry": {"type": "Point", "coordinates": [X0 + 0.00012 + k * 0.00018, Y0 + i * D + side * 0.00009]}}
      for i in range(4) for side in (-1, 1) if not (i == 0 and side < 0) and not (i == 3 and side > 0) for k in range(16)]


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def db():
    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
    await engine.dispose()


async def new_design(db, name):
    project = (await db.execute(text("SELECT id FROM projects WHERE tenant_id = :t LIMIT 1"), {"t": TENANT})).scalar_one()
    out = await service.create_design(db, TENANT, CALLER, str(project), DesignCreate(name=name))
    d = await service.load_design(db, TENANT, out.id)
    for layer, data in (("road", ROADS), ("homepass", fc(HP))):
        await service.save_inputs(db, TENANT, CALLER, d, layer, f"{layer}.geojson", "replace",
                                  parse_input_file(layer, f"{layer}.geojson", data))
    await service.boundary_from_inputs(db, TENANT, CALLER, out.id)
    return await service.load_design(db, TENANT, out.id)


async def op(db, design, **body):
    return await operations.apply_operation(db, TENANT, CALLER, design, body)


async def lengths(db, ids):
    rows = (await db.execute(text("SELECT id::text, length_m::float8, route_method, ST_AsText(geom) FROM net_cables WHERE id = ANY(:ids)"),
                             {"ids": [uuid.UUID(i) for i in ids]})).all()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


# ── A hand-built FAT ─────────────────────────────────────────

async def test_moving_a_hand_built_fat_recalculates_its_cables(db):
    d = await new_design(db, "Recalc by hand")
    fdt = (await op(db, d, op="ADD_ASSET", asset_type="FDT", lng=X0 + 0.0001, lat=Y0 + D - 0.00004))["operation"]["asset_id"]
    fat = (await op(db, d, op="ADD_ASSET", asset_type="FAT", lng=X0 + 0.0009, lat=Y0 + D + 0.00004))["operation"]["asset_id"]
    b2b = (await op(db, d, op="DRAW_CABLE", cable_category="BOX_TO_BOX",
                    **{"from": {"asset_id": fdt}, "to": {"asset_id": fat}}))["operation"]["cable_id"]
    drops = []
    for k in (4, 5, 6):
        hp = HP[16 + k]["geometry"]["coordinates"]            # Recalc Street 1, north side
        drops.append((await op(db, d, op="DRAW_CABLE", cable_category="DROP",
                               **{"from": {"asset_id": fat}, "to": {"lng": hp[0], "lat": hp[1]}}))["operation"]["cable_id"])
    before = await lengths(db, [b2b, *drops])

    # Move the FAT ~200 m east along the street: its drops can't reach any more
    r = await op(db, d, op="MOVE_ASSET", id=fat, lng=X0 + 0.0027, lat=Y0 + D + 0.00004)
    moved = {x["id"]: x for x in r["operation"]["rerouted"]}
    assert set(moved) == {b2b, *drops}
    assert moved[b2b]["route_method"] == "ROAD_GRAPH" and moved[b2b]["after_m"] > moved[b2b]["before_m"] + 150
    assert all(moved[x]["route_method"] == "DIRECT" and moved[x]["after_m"] > 150 for x in drops)
    after = await lengths(db, [b2b, *drops])
    assert after[b2b][2] != before[b2b][2]
    # The answer carries every change
    delta = r["delta"]
    changed = {q["code"]: q["change"] for q in delta["boq"]}
    assert changed["BOX_TO_BOX"] > 150 and changed["DROP"] > 300
    assert [i["code"] for i in delta["issues"]["new"]].count("DROP_TOO_LONG") == 3
    ids = {f["properties"]["id"] for f in delta["features"]}
    assert {fat, b2b, *drops} <= ids and delta["removed"] == {"assets": [], "cables": []}

    # Undo: lines, lengths and issues all back
    u = await operations.undo(db, TENANT, CALLER, d)
    assert await lengths(db, [b2b, *drops]) == before
    assert [i["code"] for i in u["delta"]["issues"]["resolved"]].count("DROP_TOO_LONG") == 3
    assert {q["code"] for q in u["delta"]["boq"]} == {"BOX_TO_BOX", "DROP"}

    # recalc=false: the ends follow, the road route is not recomputed
    r = await op(db, d, op="MOVE_ASSET", id=fat, lng=X0 + 0.0027, lat=Y0 + D + 0.00004, recalc=False)
    assert "rerouted" not in r["operation"] and (await lengths(db, [b2b]))[b2b][2] != after[b2b][2]


# ── An engine-built FAT ──────────────────────────────────────

async def test_moving_an_engine_fat_recalculates_its_cables(db):
    d = await new_design(db, "Recalc after auto")
    inputs, _notes = await auto_design.build_run_inputs(db, TENANT, d)
    run = FttxDesignRun(tenant_id=TENANT, name="recalc", status="running", design_id=d.id,
                        config=auto_design.run_config(d.engine_config))
    db.add(run)
    await db.flush()
    for k, v in inputs.items():
        db.add(FttxDesignRunLayer(run_id=run.id, tenant_id=TENANT, layer_key=k, geojson=v, feature_count=len(v["features"])))
    layers, _crs = build_input_layers(inputs)
    result = run_fttx_design(config=config_from_dict(run.config), layers=layers)
    output = FttxDesignRunOutput(run_id=run.id, tenant_id=TENANT,
                                 output_layers={k: layer_to_geojson(v) for k, v in result.output_layers.items()},
                                 boq_rows=layer_to_rows(result.output_layers["boq"]))
    db.add(output)
    await db.flush()
    await auto_design.apply_output(db, TENANT, d.id, output=output, run=run, pole_fc=inputs.get("pole"),
                                   method="AUTO", label="Auto design")
    d = await service.load_design(db, TENANT, d.id)

    # An engine FAT with drops and a box-to-box cable
    fat = (await db.execute(text("""
        SELECT a.id::text, a.asset_code, ST_X(a.geom) AS x, ST_Y(a.geom) AS y FROM net_assets a
        WHERE a.design_id = :d AND a.asset_type = 'FAT' AND a.creation_method = 'AUTO'
          AND EXISTS (SELECT 1 FROM net_cables c WHERE c.dest_asset_id = a.id AND c.cable_category = 'BOX_TO_BOX')
          AND EXISTS (SELECT 1 FROM net_cables c WHERE c.source_asset_id = a.id AND c.cable_category = 'DROP')
        ORDER BY a.asset_code LIMIT 1
    """), {"d": d.id})).one()
    r = await op(db, d, op="MOVE_ASSET", id=fat.id, lng=fat.x + 0.0003, lat=fat.y)
    cats = {x["category"] for x in r["operation"]["rerouted"]}
    assert {"BOX_TO_BOX", "DROP"} <= cats
    assert all(x["route_method"] in ("ROAD_GRAPH", "DIRECT") for x in r["operation"]["rerouted"])
    assert any(q["code"] == "BOX_TO_BOX" for q in r["delta"]["boq"])
    assert d.status in ("GENERATED", "MODIFIED")
    assert (await service.load_design(db, TENANT, d.id)).status == "MODIFIED"      # edited after the engine
    u = await operations.undo(db, TENANT, CALLER, d)
    assert {q["code"] for q in u["delta"]["boq"]} == {q["code"] for q in r["delta"]["boq"]}
