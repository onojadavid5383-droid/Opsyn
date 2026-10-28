# ============================================================
# OPSYN — tests/integration/test_manual_design_db.py
# Network GIS Phase 6 against real PostGIS and the real engine router:
# an FDT → FAT → FAT chain and a drop built entirely by hand (no auto run),
# road-routed cables, FEED links and parent FDT from the chain, BOQ and
# validation on it; every operation with its undo and redo restoring rows
# exactly (ids, geometry, links); the redo branch; snap; a frozen design.
# Harness as the other DB tests: NETWORK_GIS_DB_URL, rolled back at the end.
# ============================================================

import json
import os
import types
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

if os.environ.get("NETWORK_GIS_DB_URL"):
    import main  # noqa: F401 — registers every ORM mapper

from app.modules.design import boq_service, operations, service, snap, validation_service
from app.modules.design.inputs import parse_input_file
from app.modules.design.schemas import DesignCreate

DB_URL = os.environ.get("NETWORK_GIS_DB_URL")
pytestmark = [
    pytest.mark.skipif(not DB_URL, reason="NETWORK_GIS_DB_URL not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
CALLER = types.SimpleNamespace(id=uuid.UUID("00000000-0000-0000-0000-000000000002"), username="t", staff_profile=None)
X0, Y0, D = 3.3900, 6.6300, 0.001


def fc(features):
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


ROADS = fc([
    *({"type": "Feature", "properties": {"name": f"Hand Street {i}"},
       "geometry": {"type": "LineString", "coordinates": [[X0, Y0 + i * D], [X0 + 3 * D, Y0 + i * D]]}} for i in range(3)),
    *({"type": "Feature", "properties": {"name": f"Hand Avenue {i}"},
       "geometry": {"type": "LineString", "coordinates": [[X0 + i * D, Y0], [X0 + i * D, Y0 + 2 * D]]}} for i in range(4)),
])
HP = fc([{"type": "Feature", "properties": {"customers": 1},
          "geometry": {"type": "Point", "coordinates": [X0 + 0.0003 + k * 0.0002, Y0 + D + 0.00009]}} for k in range(5)])
POLE = fc([{"type": "Feature", "properties": {"Name": "P-1"}, "geometry": {"type": "Point", "coordinates": [X0 + 0.0021, Y0 + D - 0.00003]}}])


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


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def design(db):
    project = (await db.execute(text("SELECT id FROM projects WHERE tenant_id = :t LIMIT 1"), {"t": TENANT})).scalar_one()
    out = await service.create_design(db, TENANT, CALLER, str(project), DesignCreate(name="Hand-built block"))
    d = await service.load_design(db, TENANT, out.id)
    for layer, data in (("road", ROADS), ("homepass", HP), ("pole", POLE)):
        await service.save_inputs(db, TENANT, CALLER, d, layer, f"{layer}.geojson", "replace",
                                  parse_input_file(layer, f"{layer}.geojson", data))
    await service.boundary_from_inputs(db, TENANT, CALLER, out.id)
    return await service.load_design(db, TENANT, out.id)


async def op(db, design, **body):
    return await operations.apply_operation(db, TENANT, CALLER, design, body)


async def row(db, table, rid):
    return (await db.execute(text(f"SELECT to_jsonb(t) - 'updated_at' AS r, ST_AsText(geom) AS g FROM {table} t WHERE id = :id"),
                             {"id": uuid.UUID(str(rid))})).one_or_none()


async def codes(db, design):
    return {i["code"] for i in await validation_service.stored_issues(db, TENANT, design.id)}


IDS: dict[str, str] = {}


async def test_build_a_chain_and_a_drop_by_hand(db, design):
    r = await op(db, design, op="ADD_ASSET", asset_type="FDT", lng=X0 + 0.0001, lat=Y0 + D - 0.00004)
    IDS["fdt"] = r["operation"]["asset_id"]
    assert r["operation"]["asset_code"].startswith("FDT-") and r["history"]["can_undo"]
    IDS["fat_a"] = (await op(db, design, op="ADD_ASSET", asset_type="FAT", lng=X0 + 0.0009, lat=Y0 + D + 0.00004))["operation"]["asset_id"]
    IDS["fat_b"] = (await op(db, design, op="ADD_ASSET", asset_type="FAT", lng=X0 + 0.0021, lat=Y0 + D + 0.00004))["operation"]["asset_id"]

    b1 = await op(db, design, op="DRAW_CABLE", cable_category="BOX_TO_BOX",
                  **{"from": {"asset_id": IDS["fdt"]}, "to": {"asset_id": IDS["fat_a"]}})
    assert b1["operation"]["route_method"] == "ROAD_GRAPH" and 80 < b1["operation"]["length_m"] < 200
    IDS["b2b_1"] = b1["operation"]["cable_id"]
    IDS["b2b_2"] = (await op(db, design, op="DRAW_CABLE", cable_category="BOX_TO_BOX",
                             **{"from": {"asset_id": IDS["fat_a"]}, "to": {"asset_id": IDS["fat_b"]}}))["operation"]["cable_id"]
    drop = await op(db, design, op="DRAW_CABLE", cable_category="DROP",
                    **{"from": {"asset_id": IDS["fat_a"]}, "to": {"lng": X0 + 0.0005, "lat": Y0 + D + 0.00009}})
    assert drop["operation"]["route_method"] == "DIRECT"
    IDS["drop"] = drop["operation"]["cable_id"]

    # The cable ends sit exactly on the devices
    g = json.loads((await db.execute(text("SELECT ST_AsGeoJSON(geom) FROM net_cables WHERE id = :id"),
                                     {"id": uuid.UUID(IDS["b2b_1"])})).scalar_one())["coordinates"]
    fdt = await row(db, "net_assets", IDS["fdt"])
    assert fdt.g == f"POINT({g[0][0]} {g[0][1]})"

    # FEED links and the chain's FDT on both FATs → the chain validates
    fdt_code = fdt.r["asset_code"]
    for fat in ("fat_a", "fat_b"):
        assert (await row(db, "net_assets", IDS[fat])).r["attributes"]["parent_fdt_code"] == fdt_code
    assert (await db.execute(text("SELECT count(*) FROM net_connections WHERE design_id = :d"), {"d": design.id})).scalar_one() == 2
    assert not await codes(db, design) & {"FAT_NOT_FED", "CABLE_UNLINKED", "HAND_DRAWN_ROUTE", "EMPTY_DESIGN"}
    assert drop["summary"]["fat"] == 2 and drop["summary"]["fdt"] == 1 and drop["validation"]["errors"] == 0

    # The engine's BOQ reads the hand-built rows
    boq = await boq_service.compute_boq(db, TENANT, await service.load_design(db, TENANT, design.id))
    q = {x["code"]: x["quantity"] for x in boq["quantities"]}
    assert q["FAT"] == 2 and q["FDT"] == 1 and q["BOX_TO_BOX"] > 150 and boq["street_boq_available"]


async def test_move_undo_redo_exact(db, design):
    before_fat = await row(db, "net_assets", IDS["fat_b"])
    before_cable = await row(db, "net_cables", IDS["b2b_2"])
    r = await op(db, design, op="MOVE_ASSET", id=IDS["fat_b"], lng=X0 + 0.0025, lat=Y0 + D + 0.00004)
    assert r["operation"]["cables_followed"] == 1
    moved = await row(db, "net_cables", IDS["b2b_2"])
    end = json.loads((await db.execute(text("SELECT ST_AsGeoJSON(ST_EndPoint(geom)) FROM net_cables WHERE id = :id"),
                                       {"id": uuid.UUID(IDS["b2b_2"])})).scalar_one())["coordinates"]
    assert end == pytest.approx([X0 + 0.0025, Y0 + D + 0.00004])

    u = await operations.undo(db, TENANT, CALLER, design)
    assert u["operation"]["label"].startswith("Undid: Move") and u["history"]["can_redo"]
    assert (await row(db, "net_assets", IDS["fat_b"])).g == before_fat.g
    assert (await row(db, "net_cables", IDS["b2b_2"])).g == before_cable.g
    await operations.redo(db, TENANT, CALLER, design)
    assert (await row(db, "net_cables", IDS["b2b_2"])).g == moved.g


async def test_delete_restores_rows_links_and_cables(db, design):
    counts = lambda: db.execute(text("""
        SELECT (SELECT count(*) FROM net_assets WHERE design_id = :d), (SELECT count(*) FROM net_cables WHERE design_id = :d),
               (SELECT count(*) FROM net_connections WHERE design_id = :d)"""), {"d": design.id})
    before = (await counts()).one()
    r = await op(db, design, op="DELETE_ASSET", id=IDS["fat_a"])
    assert r["operation"]["removed_cables"] == 3                   # both box-to-box and the drop
    await operations.undo(db, TENANT, CALLER, design)
    assert tuple((await counts()).one()) == tuple(before)
    assert await row(db, "net_cables", IDS["drop"]) is not None      # same ids back


async def test_attrs_split_extend_redraw_connect(db, design):
    await op(db, design, op="UPDATE_ATTRS", target="asset", id=IDS["fat_b"], changes={"used_capacity": 12})
    assert "FAT_OVER_CAPACITY" in await codes(db, design)
    await operations.undo(db, TENANT, CALLER, design)
    assert "FAT_OVER_CAPACITY" not in await codes(db, design)

    original = await row(db, "net_cables", IDS["b2b_1"])
    mid = json.loads((await db.execute(text("SELECT ST_AsGeoJSON(ST_LineInterpolatePoint(geom, 0.5)) FROM net_cables WHERE id = :id"),
                                       {"id": uuid.UUID(IDS["b2b_1"])})).scalar_one())["coordinates"]
    s = await op(db, design, op="SPLIT_CABLE", id=IDS["b2b_1"], lng=mid[0], lat=mid[1], insert_asset_type="CLOSURE")
    assert s["operation"]["asset_id"] and s["operation"]["cable_id"]
    parts = (await db.execute(text("""
        SELECT sum(length_m)::float8 FROM net_cables WHERE id = ANY(:ids)
    """), {"ids": [uuid.UUID(IDS["b2b_1"]), uuid.UUID(s["operation"]["cable_id"])]})).scalar_one()
    assert abs(parts - float(original.r["length_m"])) < 0.5
    await operations.undo(db, TENANT, CALLER, design)
    assert (await row(db, "net_cables", IDS["b2b_1"])).g == original.g
    assert await row(db, "net_cables", s["operation"]["cable_id"]) is None

    await op(db, design, op="EXTEND_CABLE", id=IDS["drop"], to={"lng": X0 + 0.0005, "lat": Y0 + D + 0.0002}, route="straight")
    await op(db, design, op="EDIT_CABLE_GEOM", id=IDS["b2b_2"],
             coordinates=[[X0 + 0.0009, Y0 + D + 0.00004], [X0 + 0.0015, Y0 + D + 0.0002], [X0 + 0.0025, Y0 + D + 0.00004]])
    assert "HAND_DRAWN_ROUTE" in await codes(db, design)
    await operations.undo(db, TENANT, CALLER, design)
    await operations.undo(db, TENANT, CALLER, design)
    assert "HAND_DRAWN_ROUTE" not in await codes(db, design)

    with pytest.raises(HTTPException) as exc:
        await op(db, design, op="CONNECT", source_id=IDS["fdt"], dest_id=IDS["fat_a"])
    assert exc.value.status_code == 409
    await op(db, design, op="CONNECT", source_id=IDS["fdt"], dest_id=IDS["fat_b"])
    await op(db, design, op="DISCONNECT", source_id=IDS["fdt"], dest_id=IDS["fat_b"])


async def test_a_new_edit_ends_the_redo_branch(db, design):
    await operations.undo(db, TENANT, CALLER, design)
    assert (await operations.history(db, TENANT, design))["can_redo"]
    await op(db, design, op="ADD_ASSET", asset_type="POLE", lng=X0 + 0.0015, lat=Y0 + 0.00004)
    h = await operations.history(db, TENANT, design)
    assert not h["can_redo"] and h["undo_label"].startswith("Add POLE-")


async def test_undo_everything_then_redo_everything(db, design):
    size = lambda: db.execute(text("SELECT (SELECT count(*) FROM net_assets WHERE design_id = :d) + "
                                   "(SELECT count(*) FROM net_cables WHERE design_id = :d)"), {"d": design.id})
    full = (await size()).scalar_one()
    n = (await operations.history(db, TENANT, design))["applied"]
    for _ in range(n):
        await operations.undo(db, TENANT, CALLER, design)
    assert (await size()).scalar_one() == 0
    with pytest.raises(HTTPException):
        await operations.undo(db, TENANT, CALLER, design)
    for _ in range(n):
        await operations.redo(db, TENANT, CALLER, design)
    assert (await size()).scalar_one() == full


async def test_refusals(db, design):
    for body, msg in (({"op": "NOPE"}, "Unknown operation"), ({"op": "ADD_ASSET", "asset_type": "TOASTER", "lng": 1, "lat": 1}, "Unknown asset type"),
                      ({"op": "DRAW_CABLE", "cable_category": "BOX_TO_BOX", "from": {"lng": X0 + 0.0001, "lat": Y0 + 0.00002},
                        "to": {"lng": X0 + 0.0001, "lat": Y0 + 0.00002}, "route": "straight"}, "same spot"),
                      ({"op": "MOVE_ASSET", "id": str(uuid.uuid4()), "lng": 1, "lat": 1}, "not in this design")):
        with pytest.raises(HTTPException) as exc:
            await operations.apply_operation(db, TENANT, CALLER, design, body)
        assert msg in exc.value.detail
    await db.execute(text("UPDATE designs SET status = 'UNDER_REVIEW' WHERE id = :d"), {"d": design.id})
    await db.refresh(design)
    try:
        with pytest.raises(HTTPException) as exc:
            await op(db, design, op="ADD_ASSET", asset_type="FAT", lng=X0, lat=Y0)
        assert exc.value.status_code == 409
    finally:
        await db.execute(text("UPDATE designs SET status = 'MODIFIED' WHERE id = :d"), {"d": design.id})
        await db.refresh(design)


async def test_snap(db, design):
    fdt = await row(db, "net_assets", IDS["fdt"])
    x, y = map(float, fdt.g[6:-1].split())
    s = await snap.snap(db, TENANT, design, x + 0.00003, y, 15)
    assert s["snapped"] and s["kind"] == "asset" and s["id"] == IDS["fdt"]
    s = await snap.snap(db, TENANT, design, X0 + 0.00031, Y0 + D + 0.0001, 8, ["homepass"])
    assert s["kind"] == "homepass"
    s = await snap.snap(db, TENANT, design, X0 + 0.0021, Y0 + D - 0.00002, 8, ["pole_input"])
    assert s["kind"] == "pole_input" and s["code"] == "P-1"
    # Beside the road, 3 m towards the click
    s = await snap.snap(db, TENANT, design, X0 + 0.0016, Y0 + 2 * D - 0.0001, 15, ["road"])
    assert s["kind"] == "road" and abs(s["lat"] - (Y0 + 2 * D - 3 / 111_320)) < 2e-6
    assert not (await snap.snap(db, TENANT, design, X0 + 0.05, Y0 + 0.05, 10))["snapped"]
    # Mid-block, ~55 m from every road: stays where clicked (a 2.5x road reach used to drag it onto a street)
    assert not (await snap.snap(db, TENANT, design, X0 + 0.0015, Y0 + 0.0005, 30, ["road"]))["snapped"]
