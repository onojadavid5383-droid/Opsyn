# ============================================================
# OPSYN — tests/integration/test_deployment_db.py
# Network GIS Phase 10 against real PostGIS: the whole journey.
# project → design → design + BOQ approved (rows follow the lifecycle) →
# deploy (APPROVED → CONSTRUCTION, designed geometry kept) → install / test /
# verify / fail with legal transitions only → as-built capture and the
# variance report → promote: the SAME rows become live (ACTIVE, no
# design_id, lineage kept, audit "promote"), nothing duplicated, the live
# trace walks them; code clashes and unverified rows refuse promotion.
# Also: every geometry column of the design tables is in the version /
# operation-log geometry lists. Harness: NETWORK_GIS_DB_URL, rolled back.
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

from app.core.context import tenant_id_ctx
from app.modules.approval import service as approval
from app.modules.deployment import service as deployment
from app.modules.design import operations, service, versions
from app.modules.design.inputs import parse_input_file
from app.modules.design.schemas import DesignCreate
from app.modules.network import topology_service

DB_URL = os.environ.get("NETWORK_GIS_DB_URL")
pytestmark = [
    pytest.mark.skipif(not DB_URL, reason="NETWORK_GIS_DB_URL not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
tenant_id_ctx.set(str(TENANT))
X0, Y0, D = 3.4600, 6.7000, 0.001


def fc(features):
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


ROADS = fc([{"type": "Feature", "properties": {"name": f"B Street {i}"},
             "geometry": {"type": "LineString", "coordinates": [[X0, Y0 + i * D], [X0 + 2 * D, Y0 + i * D]]}} for i in range(2)]
           + [{"type": "Feature", "properties": {"name": f"B Avenue {i}"},
               "geometry": {"type": "LineString", "coordinates": [[X0 + i * D, Y0], [X0 + i * D, Y0 + D]]}} for i in range(3)])
HP = fc([{"type": "Feature", "properties": {"customers": 1},
          "geometry": {"type": "Point", "coordinates": [X0 + 0.0003 + k * 0.0002, Y0 + 0.00008]}} for k in range(4)])


async def user(db, username):
    r = (await db.execute(text("""
        SELECT u.id, u.username, u.role_id, r.level, sp.department_id FROM users u JOIN roles r ON r.id = u.role_id
        LEFT JOIN staff_profiles sp ON sp.user_id = u.id WHERE u.username = :n
    """), {"n": username})).one()
    return types.SimpleNamespace(id=r.id, username=r.username, role_id=r.role_id, role=types.SimpleNamespace(level=r.level),
                                 staff_profile=types.SimpleNamespace(department_id=r.department_id) if r.department_id else None)


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
async def people(db):
    return {"engineer": await user(db, "manager.test"), "admin": await user(db, "david.onoja")}


async def build(db, name, who):
    project = (await db.execute(text("SELECT id FROM projects WHERE tenant_id = :t LIMIT 1"), {"t": TENANT})).scalar_one()
    out = await service.create_design(db, TENANT, who, str(project), DesignCreate(name=name))
    d = await service.load_design(db, TENANT, out.id)
    for layer, data in (("road", ROADS), ("homepass", HP)):
        await service.save_inputs(db, TENANT, who, d, layer, f"{layer}.geojson", "replace", parse_input_file(layer, "x.geojson", data))
    await service.boundary_from_inputs(db, TENANT, who, out.id)
    op = lambda **b: operations.apply_operation(db, TENANT, who, d, b)  # noqa: E731
    fdt = (await op(op="ADD_ASSET", asset_type="FDT", lng=X0 + 0.0001, lat=Y0 - 0.00004))["operation"]["asset_id"]
    fat = (await op(op="ADD_ASSET", asset_type="FAT", lng=X0 + 0.0008, lat=Y0 + 0.00004))["operation"]["asset_id"]
    await op(op="DRAW_CABLE", cable_category="BOX_TO_BOX", **{"from": {"asset_id": fdt}, "to": {"asset_id": fat}})
    return await service.load_design(db, TENANT, out.id), fdt, fat


async def approve_all(db, people, d):
    eng, admin = people["engineer"], people["admin"]
    r = await approval.submit_design(db, TENANT, eng, d, None)
    for _ in range(2):
        await approval.decide(db, TENANT, admin, r["id"], "APPROVE", None)
    d = await service.load_design(db, TENANT, d.id)
    b = await approval.submit_boq(db, TENANT, eng, d, None)
    for _ in range(2):
        await approval.decide(db, TENANT, admin, b["id"], "APPROVE", None)
    return await service.load_design(db, TENANT, d.id)


async def states(db, design_id):
    return {r[0] for r in (await db.execute(text("""
        SELECT lifecycle_status FROM net_assets WHERE design_id = :d AND deleted_at IS NULL
        UNION SELECT lifecycle_status FROM net_cables WHERE design_id = :d AND deleted_at IS NULL
    """), {"d": design_id})).all()}


async def items(db, design_id):
    rows = (await db.execute(text("""
        SELECT 'asset' AS kind, id::text AS id FROM net_assets WHERE design_id = :d AND deleted_at IS NULL AND parent_id IS NULL
        UNION ALL SELECT 'cable', id::text FROM net_cables WHERE design_id = :d AND deleted_at IS NULL
    """), {"d": design_id})).all()
    return [{"kind": r.kind, "id": r.id} for r in rows]


S: dict = {}


async def test_geometry_lists_cover_every_geometry_column(db):
    cols = (await db.execute(text("""
        SELECT f_table_name, f_geometry_column FROM geometry_columns
        WHERE f_table_name IN ('net_assets', 'net_cables', 'net_connections')
    """))).all()
    for table, col in cols:
        assert col in operations.GEOM_COLS[table], (table, col)
        assert col in versions.GEOM[table], (table, col)


async def test_not_deployable_until_design_and_boq_approved(db, people):
    d, fdt, fat = await build(db, "Deploy — Bode", people["engineer"])
    S.update(design=d, fdt=fdt, fat=fat)
    with pytest.raises(HTTPException) as exc:
        await deployment.deploy(db, TENANT, people["admin"], d, None)
    assert exc.value.status_code == 409 and "not approved" in exc.value.detail
    d = await approve_all(db, people, d)
    assert d.status == "APPROVED" and await states(db, d.id) == {"APPROVED"}      # the rows followed the approval
    S["design"] = d


async def test_deploy_moves_to_construction_and_keeps_the_design(db, people):
    d = S["design"]
    p = await deployment.deploy(db, TENANT, people["admin"], d, "Crew A")
    assert p["deployment"]["status"] == "IN_PROGRESS" and p["deployment"]["note"] == "Crew A"
    assert await states(db, d.id) == {"CONSTRUCTION"}
    assert p["installed"] == 0 and p["items"] == 3 and p["fats"] == {"total": 1, "installed": 0, "verified": 0}
    assert p["cable_m"]["planned"] > 0 and p["cable_m"]["installed"] == 0
    assert p["per_fdt"] and p["per_fdt"][0]["fats"] == 1
    kept = (await db.execute(text("""
        SELECT bool_and(design_geom IS NOT NULL AND ST_Equals(design_geom, geom)) FROM net_assets WHERE design_id = :d
    """), {"d": d.id})).scalar_one()
    assert kept
    with pytest.raises(HTTPException) as exc:                                    # once
        await deployment.deploy(db, TENANT, people["admin"], d, None)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:                                    # and not reopened under the field
        await approval.reopen(db, TENANT, people["engineer"], d)
    assert exc.value.status_code == 409


async def test_field_steps_follow_the_lifecycle(db, people):
    d, admin = S["design"], people["admin"]
    fat = [{"kind": "asset", "id": S["fat"]}]
    r = await deployment.advance(db, TENANT, admin, d, fat, "test", None)          # not installed yet
    assert r["changed"] == [] and r["refused"] and r["refused"][0]["state"] == "CONSTRUCTION"
    with pytest.raises(HTTPException):
        await deployment.advance(db, TENANT, admin, d, fat, "fail", "  ")          # a failure needs a note
    r = await deployment.advance(db, TENANT, admin, d, fat, "install", None)
    assert r["changed"][0]["to"] == "INSTALLED" and r["progress"]["fats"]["installed"] == 1
    r = await deployment.advance(db, TENANT, admin, d, fat, "test", None)
    assert r["changed"][0]["to"] == "TESTING"
    r = await deployment.advance(db, TENANT, admin, d, fat, "fail", "Splitter loss too high")
    assert r["changed"][0] == {"code": r["changed"][0]["code"], "from": "TESTING", "to": "INSTALLED"}
    note = (await db.execute(text("SELECT attributes->>'field_note' FROM net_assets WHERE id = :i"), {"i": S["fat"]})).scalar_one()
    assert note == "Splitter loss too high"
    # every step is in the audit trail with its actor
    steps = (await db.execute(text("""
        SELECT new_data->>'lifecycle_status' FROM network_audit_log WHERE entity_id = :i AND 'lifecycle_status' = ANY(changed_fields)
        ORDER BY occurred_at
    """), {"i": S["fat"]})).scalars().all()
    assert steps[-3:] == ["INSTALLED", "TESTING", "INSTALLED"]


async def test_asbuilt_and_variance(db, people):
    d, admin = S["design"], people["admin"]
    cable = (await db.execute(text("SELECT id::text, geom FROM net_cables WHERE design_id = :d"), {"d": d.id})).one()
    with pytest.raises(HTTPException) as exc:                                    # the cable isn't installed yet
        await deployment.capture_asbuilt(db, TENANT, admin, d, "cable", cable.id,
                                         {"type": "LineString", "coordinates": [[X0, Y0], [X0 + D, Y0]]})
    assert exc.value.status_code == 409
    await deployment.advance(db, TENANT, admin, d, [{"kind": "cable", "id": cable.id}], "install", None)
    with pytest.raises(HTTPException):
        await deployment.capture_asbuilt(db, TENANT, admin, d, "cable", cable.id, {"type": "Point", "coordinates": [X0, Y0]})
    # installed along a detour: longer than designed
    detour = {"type": "LineString", "coordinates": [[X0 + 0.0001, Y0 - 0.00004], [X0 + 0.0001, Y0 + 0.0004],
                                                    [X0 + 0.0008, Y0 + 0.0004], [X0 + 0.0008, Y0 + 0.00004]]}
    p = await deployment.capture_asbuilt(db, TENANT, admin, d, "cable", cable.id, detour)
    v = next(x for x in p["variance"] if x["kind"] == "cable")
    assert v["asbuilt_m"] > v["design_m"] and v["difference_m"] == pytest.approx(v["asbuilt_m"] - v["design_m"], abs=0.1)
    row = (await db.execute(text("SELECT route_method, length_m FROM net_cables WHERE id = :i"), {"i": cable.id})).one()
    assert row.route_method == "IMPORTED"
    # the FAT was mounted 20 m or so from its designed spot
    p = await deployment.capture_asbuilt(db, TENANT, admin, d, "asset", S["fat"],
                                         {"type": "Point", "coordinates": [X0 + 0.0008, Y0 + 0.00022]})
    moved = next(x for x in p["variance"] if x["kind"] == "asset")["moved_m"]
    assert 15 < moved < 25


async def test_promotion_needs_everything_verified(db, people):
    d, admin = S["design"], people["admin"]
    with pytest.raises(HTTPException) as exc:
        await deployment.promote(db, TENANT, admin, d)
    assert exc.value.status_code == 409 and "not verified" in exc.value.detail
    for action in ("install", "verify"):
        await deployment.advance(db, TENANT, admin, d, await items(db, d.id), action, None)
    p = await deployment.progress(db, TENANT, d)
    assert p["verified_pct"] == 100.0 and p["ready_to_promote"] and await states(db, d.id) == {"VERIFIED"}


async def test_live_code_clash_refuses_promotion(db, people):
    d = S["design"]
    code = (await db.execute(text("SELECT asset_code FROM net_assets WHERE id = :i"), {"i": S["fat"]})).scalar_one()
    clash = (await db.execute(text("""
        INSERT INTO net_assets (tenant_id, asset_code, asset_type, geom, lifecycle_status)
        VALUES (:t, :c, 'FAT', ST_SetSRID(ST_MakePoint(:x, :y), 4326), 'ACTIVE') RETURNING id
    """), {"t": TENANT, "c": code, "x": X0 + 0.01, "y": Y0})).scalar_one()
    with pytest.raises(HTTPException) as exc:
        await deployment.promote(db, TENANT, people["admin"], d)
    assert exc.value.status_code == 409 and code in exc.value.detail
    await db.execute(text("DELETE FROM net_assets WHERE id = :i"), {"i": clash})


async def test_promote_makes_the_same_rows_live(db, people):
    d = S["design"]
    ids = {i["id"] for i in await items(db, d.id)}
    live_before = (await db.execute(text("SELECT count(*) FROM net_assets WHERE design_id IS NULL AND deleted_at IS NULL"))).scalar_one()
    out = await deployment.promote(db, TENANT, people["admin"], d)
    assert out["design_status"] == "DEPLOYED" and out["promoted"]["assets"] == 2 and out["promoted"]["cables"] == 1
    rows = (await db.execute(text("""
        SELECT id::text, design_id, lifecycle_status, lineage_id FROM net_assets WHERE id = ANY(CAST(:ids AS uuid[]))
        UNION ALL SELECT id::text, design_id, lifecycle_status, lineage_id FROM net_cables WHERE id = ANY(CAST(:ids AS uuid[]))
    """), {"ids": list(ids)})).all()
    assert len(rows) == 3                                                        # the same rows, not copies
    assert all(r.design_id is None and r.lifecycle_status == "ACTIVE" and r.lineage_id == d.id for r in rows)
    live_after = (await db.execute(text("SELECT count(*) FROM net_assets WHERE design_id IS NULL AND deleted_at IS NULL"))).scalar_one()
    assert live_after == live_before + 2
    assert (await db.execute(text("SELECT count(*) FROM net_assets WHERE design_id = :d"), {"d": d.id})).scalar_one() == 0
    # the audit says "promote", and the entry still belongs to the design's history
    acts = (await db.execute(text("SELECT DISTINCT action FROM network_audit_log WHERE entity_id = :i AND design_id = :d"),
                             {"i": S["fat"], "d": d.id})).scalars().all()
    assert "promote" in acts
    # the as-built state is its own frozen version
    v = await versions.current(db, await service.load_design(db, TENANT, d.id))
    assert v.snapshot is not None and v.label.startswith("As built")
    # the live network traces through the promoted FDT to its FAT
    t = await topology_service.trace(db, TENANT, S["fdt"], "downstream")
    assert S["fat"] in {h.asset.id for h in t.hops}
    dep = await deployment.progress(db, TENANT, d)
    assert dep["deployment"]["status"] == "PROMOTED" and dep["deployment"]["summary"]["assets"] == 2
    with pytest.raises(HTTPException):                                           # nothing left to deploy
        await deployment.advance(db, TENANT, people["admin"], d, [{"kind": "asset", "id": S["fat"]}], "install", None)
