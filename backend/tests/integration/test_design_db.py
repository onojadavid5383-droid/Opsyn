# ============================================================
# OPSYN — tests/integration/test_design_db.py
# Network GIS Phase 4 against real PostGIS and the real FTTx engine:
#   design create (V1) → inputs (GeoJSON; rejected file writes nothing;
#   append / replace) → boundary from inputs → road-graph route →
#   working set → BOQ (quantities + the engine's street BOQ) → validation
#   (engine rule values, topology, boundary) → features / summary →
#   tenant isolation.
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

from app.modules.design import boq_service, routing_service, service, validation_service
from app.modules.design.inputs import parse_input_file
from app.modules.design.schemas import DesignCreate, DesignUpdate

DB_URL = os.environ.get("NETWORK_GIS_DB_URL")
pytestmark = [
    pytest.mark.skipif(not DB_URL, reason="NETWORK_GIS_DB_URL not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

TENANT_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
TENANT_B = uuid.UUID("00000000-0000-0000-0000-0000000000b5")
CALLER = types.SimpleNamespace(id=uuid.UUID("00000000-0000-0000-0000-000000000002"), username="t", staff_profile=None)

# A 3x3 block grid (~110 m blocks) near Allen Avenue
X0, Y0, D = 3.3500, 6.5980, 0.001


def fc(features):
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


ROADS = fc([
    *({"type": "Feature", "properties": {"name": f"Street {i}"},
       "geometry": {"type": "LineString", "coordinates": [[X0, Y0 + i * D], [X0 + 3 * D, Y0 + i * D]]}} for i in range(4)),
    *({"type": "Feature", "properties": {"name": f"Avenue {i}"},
       "geometry": {"type": "LineString", "coordinates": [[X0 + i * D, Y0], [X0 + i * D, Y0 + 3 * D]]}} for i in range(4)),
])
HOMEPASSES = fc([{"type": "Feature", "properties": {"Customers": 2 if i % 2 else "3"},
                  "geometry": {"type": "Point", "coordinates": [X0 + 0.0002 + i * 0.0004, Y0 + 0.00015]}} for i in range(6)])


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def db():
    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        await session.execute(text("INSERT INTO tenants (id, name, slug) VALUES (:b, 'Design test B', 'design-test-b') "
                                   "ON CONFLICT (id) DO NOTHING"), {"b": TENANT_B})
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def design(db):
    project = (await db.execute(text("SELECT id FROM projects WHERE tenant_id = :t LIMIT 1"), {"t": TENANT_A})).scalar_one()
    out = await service.create_design(db, TENANT_A, CALLER, str(project), DesignCreate(name="  Allen Ave phase 1 "))
    return out


async def load(db, design):
    return await service.load_design(db, TENANT_A, design.id)


# ── Container ────────────────────────────────────────────────

async def test_create_design_with_version_one(db, design):
    assert design.name == "Allen Ave phase 1" and design.status == "DRAFT"
    assert design.current_version.version_no == 1 and design.current_version.creation_method == "INITIAL"
    with pytest.raises(HTTPException) as exc:
        await service.create_design(db, TENANT_A, CALLER, str(uuid.uuid4()), DesignCreate(name="x"))
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await service.create_design(db, TENANT_A, CALLER, design.project_id,
                                    DesignCreate(name="x", engine_config={"not_a_setting": 1}))
    assert exc.value.status_code == 422


# ── Inputs ───────────────────────────────────────────────────

async def test_inputs_upload_reject_append_replace(db, design):
    d = await load(db, design)
    res = await service.save_inputs(db, TENANT_A, CALLER, d, "road", "roads.geojson", "replace",
                                    parse_input_file("road", "roads.geojson", ROADS))
    assert res["status"] == "saved" and res["feature_count"] == 8

    bad = fc([{"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [3.35, 6.6]}},
              {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": [[3.35, 6.6], [300, 6.6]]}}])
    res = await service.save_inputs(db, TENANT_A, CALLER, d, "road", "bad.geojson", "append",
                                    parse_input_file("road", "bad.geojson", bad))
    assert res["status"] == "rejected" and len(res["errors"]) == 2
    counts = {i["layer_key"]: i["feature_count"] for i in await service.list_inputs(db, TENANT_A, d)}
    assert counts["road"] == 8                                   # nothing written

    res = await service.save_inputs(db, TENANT_A, CALLER, d, "homepass", "hp.geojson", "replace",
                                    parse_input_file("homepass", "hp.geojson", HOMEPASSES))
    assert res["feature_count"] == 6
    extra = fc([{"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [X0 + 0.0025, Y0 + 0.0028]}}])
    res = await service.save_inputs(db, TENANT_A, CALLER, d, "homepass", "one.geojson", "append",
                                    parse_input_file("homepass", "one.geojson", extra))
    assert res["warnings"] == ["1 homepasses had no customer count and were counted as 1"]
    summary = await service.summary(db, TENANT_A, d)
    assert summary["homepasses"] == 7 and summary["customers"] == 3 + 2 + 3 + 2 + 3 + 2 + 1

    feats = await service.input_features(db, TENANT_A, d, "road")
    assert len(feats["features"]) == 8 and feats["features"][0]["properties"]["layer_key"] == "road"


async def test_boundary_from_inputs_and_validation_of_drawn_ones(db, design):
    out = await service.boundary_from_inputs(db, TENANT_A, CALLER, design.id)
    assert out.boundary["type"] == "MultiPolygon" and out.bbox[0] < X0 < out.bbox[2]
    bow_tie = {"type": "Polygon", "coordinates": [[[3.35, 6.60], [3.36, 6.61], [3.36, 6.60], [3.35, 6.61], [3.35, 6.60]]]}
    with pytest.raises(HTTPException) as exc:
        await service.update_design(db, TENANT_A, CALLER, design.id, DesignUpdate(boundary=bow_tie))
    assert exc.value.status_code == 422 and "not a valid area" in exc.value.detail


# ── Routing ──────────────────────────────────────────────────

async def test_route_follows_the_roads(db, design):
    d = await load(db, design)
    r = await routing_service.route(db, TENANT_A, d, {"lng": X0 + 0.5 * D, "lat": Y0 + 0.00002},
                                    {"lng": X0 + 2.5 * D, "lat": Y0 + 3 * D - 0.00002})
    assert r["route_method"] == "ROAD_GRAPH" and len(r["geometry"]["coordinates"]) >= 4
    assert r["length_m"] > r["straight_line_m"] * 1.3              # round the blocks, not through them
    far = await routing_service._resolve_end(db, TENANT_A, d.id, {"lng": 4.0, "lat": 7.0}, "end")
    assert far[0] == 4.0


# ── Working set, BOQ, validation ─────────────────────────────

async def _asset(db, design_id, code, type_, lng, lat, **extra):
    return (await db.execute(text("""
        INSERT INTO net_assets (tenant_id, design_id, asset_code, asset_type, geom, lifecycle_status, creation_method,
                                capacity, used_capacity, attributes)
        VALUES (:t, :d, :c, :ty, ST_SetSRID(ST_MakePoint(:x, :y), 4326), 'DESIGNED', 'MANUAL', :cap, :used, CAST(:attrs AS jsonb))
        RETURNING id
    """), {"t": TENANT_A, "d": design_id, "c": code, "ty": type_, "x": lng, "y": lat,
           "cap": extra.get("capacity"), "used": extra.get("used"), "attrs": json.dumps(extra.get("attrs", {}))})).scalar_one()


async def test_boq_and_validation_on_a_working_set(db, design):
    did = uuid.UUID(design.id)
    fdt = await _asset(db, did, "FDT-D-01", "FDT", X0 + D, Y0 + 0.00003, capacity=64)
    fat1 = await _asset(db, did, "FAT-D-01", "FAT", X0 + 0.0006, Y0 + 0.00003, capacity=8, used=6, attrs={"wing": "A"})
    fat2 = await _asset(db, did, "FAT-D-02", "FAT", X0 + 0.0022, Y0 + 0.00003, capacity=8, used=12, attrs={"wing": "A"})
    await _asset(db, did, "FAT-D-03", "FAT", X0 + 0.0028, Y0 + 0.0029, capacity=8, used=2)   # nothing feeds it
    await _asset(db, did, "POLE-D-99", "POLE", 3.40, 6.70)                                       # outside the boundary
    for fat in (fat1, fat2):
        await db.execute(text("""
            INSERT INTO net_connections (tenant_id, design_id, source_asset_id, dest_asset_id, connection_type)
            VALUES (:t, :d, :s, :f, 'FEED')
        """), {"t": TENANT_A, "d": did, "s": fdt, "f": fat})
    await db.execute(text("""
        INSERT INTO net_cables (tenant_id, design_id, asset_code, cable_category, geom, route_method, source_asset_id,
                                dest_asset_id, fiber_count, lifecycle_status, creation_method)
        VALUES (:t, :d, 'B2B-D-01', 'BOX_TO_BOX', ST_SetSRID(ST_MakeLine(ST_MakePoint(:x1, :y), ST_MakePoint(:x2, :y)), 4326),
                'ROAD_GRAPH', :s, :f, 12, 'DESIGNED', 'MANUAL'),
               (:t, :d, 'DRP-D-01', 'DROP', ST_SetSRID(ST_MakeLine(ST_MakePoint(:x1, :y), ST_MakePoint(:x1, :y2)), 4326),
                'MANUAL_GEOMETRY', :f, NULL, 2, 'DESIGNED', 'MANUAL'),
               (:t, :d, 'DST-D-01', 'DISTRIBUTION', ST_SetSRID(ST_MakeLine(ST_MakePoint(:x2, :y), ST_MakePoint(:x2, :y3)), 4326),
                'ROAD_GRAPH', :s, NULL, 12, 'DESIGNED', 'MANUAL')
    """), {"t": TENANT_A, "d": did, "x1": X0 + 0.0006, "x2": X0 + D, "y": Y0 + 0.00003, "y2": Y0 + 0.002, "y3": Y0 + 0.0008,
           "s": fdt, "f": fat1})

    d = await load(db, design)
    boq = await boq_service.compute_boq(db, TENANT_A, d)
    q = {x["item"]: x["quantity"] for x in boq["quantities"]}
    assert q["FAT"] == 3 and q["FDT"] == 1 and q["Pole (new)"] == 1
    assert 40 < q["Box to box cable, 12 fibres"] < 50 and 200 < q["Drop cable, 2 fibres"] < 230
    assert boq["street_boq_available"] and boq["streets"]
    streets = {r["street_name"]: r for r in boq["streets"] if r.get("street_name")}
    assert "Street 0" in streets and streets["Street 0"]["total_fat"] >= 2        # the engine put the FATs on their street

    result = await validation_service.validate(db, TENANT_A, d)
    codes = {i["code"] for i in result["issues"]}
    assert {"FAT_OVER_CAPACITY", "FAT_NOT_FED", "DROP_TOO_LONG", "HAND_DRAWN_ROUTE",
            "CABLE_UNLINKED", "OUTSIDE_BOUNDARY", "FDT_NOT_FED"} <= codes
    assert "NO_ROADS" not in codes and "NO_BOUNDARY" not in codes
    unlinked = [i["message"] for i in result["issues"] if i["code"] == "CABLE_UNLINKED"]
    assert unlinked == ["DST-D-01 is not attached to an asset at one end."]      # the drop needs only its FAT
    over = next(i for i in result["issues"] if i["code"] == "FAT_OVER_CAPACITY")
    assert over["asset_id"] == str(fat2) and over["geometry"]["type"] == "Point" and over["metadata"]["limit"] == 8
    assert result["summary"]["errors"] >= 3 and result["summary"]["validated_at"]
    assert result["issues"][0]["severity"] == "ERROR"                             # errors first
    again = await validation_service.validate(db, TENANT_A, d)                    # replaces, never piles up
    assert len(again["issues"]) == len(result["issues"])

    summary = await service.summary(db, TENANT_A, d)
    assert (summary["fdt"], summary["fat"], summary["errors"]) == (1, 3, result["summary"]["errors"])
    feats = await service.working_set_features(db, TENANT_A, d)
    kinds = [f["properties"]["kind"] for f in feats["features"]]
    assert kinds.count("asset") == 5 and kinds.count("cable") == 3


async def test_empty_design_validation_is_informative(db, design):
    other = await service.create_design(db, TENANT_A, CALLER, design.project_id, DesignCreate(name="Empty"))
    result = await validation_service.validate(db, TENANT_A, await load(db, other))
    assert {i["code"] for i in result["issues"]} == {"NO_BOUNDARY", "NO_ROADS", "EMPTY_DESIGN"}
    boq = await boq_service.compute_boq(db, TENANT_A, await load(db, other))
    assert not boq["street_boq_available"] and "Upload the design's roads first" in boq["notes"][0]


async def test_designs_are_tenant_isolated(db, design):
    with pytest.raises(HTTPException) as exc:
        await service.load_design(db, TENANT_B, design.id)
    assert exc.value.status_code == 404


async def test_a_design_in_review_or_later_is_frozen(db, design):
    d = await load(db, design)
    await db.execute(text("UPDATE designs SET status = 'UNDER_REVIEW' WHERE id = :id"), {"id": d.id})
    await db.refresh(d)
    try:
        for attempt in (
            lambda: service.save_inputs(db, TENANT_A, CALLER, d, "pole", "p.geojson", "append",
                                        parse_input_file("pole", "p.geojson", fc([{"type": "Feature", "properties": {},
                                            "geometry": {"type": "Point", "coordinates": [X0, Y0]}}]))),
            lambda: service.delete_inputs(db, TENANT_A, CALLER, d, "road"),
            lambda: service.boundary_from_inputs(db, TENANT_A, CALLER, design.id),
            lambda: service.update_design(db, TENANT_A, CALLER, design.id, DesignUpdate(boundary=None)),
        ):
            with pytest.raises(HTTPException) as exc:
                await attempt()
            assert exc.value.status_code == 409 and "under review" in exc.value.detail
        # Renaming is not content
        out = await service.update_design(db, TENANT_A, CALLER, design.id, DesignUpdate(name="Allen Ave (review)"))
        assert out.name == "Allen Ave (review)"
    finally:
        await db.execute(text("UPDATE designs SET status = 'DRAFT' WHERE id = :id"), {"id": d.id})
