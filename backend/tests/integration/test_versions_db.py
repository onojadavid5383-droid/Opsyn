# ============================================================
# OPSYN — tests/integration/test_versions_db.py
# Network GIS Phase 8 against real PostGIS: "no design state is ever
# lost". The audit trigger records every change with the actor (updates as
# changed fields only); a saved version is frozen and readable later;
# compare finds added / removed / moved; replacing inputs checkpoints the
# state first; restore brings back the working set AND the inputs as a new
# version, keeping the state it replaced; bulk replacement writes one
# summary audit row. Harness: NETWORK_GIS_DB_URL, rolled back at the end.
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

from app.modules.design import audit, operations, service, versions
from app.modules.design.inputs import parse_input_file
from app.modules.design.schemas import DesignCreate

DB_URL = os.environ.get("NETWORK_GIS_DB_URL")
pytestmark = [
    pytest.mark.skipif(not DB_URL, reason="NETWORK_GIS_DB_URL not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
CALLER = types.SimpleNamespace(id=uuid.UUID("00000000-0000-0000-0000-000000000002"), username="versions.tester", staff_profile=None)
X0, Y0, D = 3.4300, 6.6700, 0.001


def fc(features):
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


ROADS = fc([{"type": "Feature", "properties": {"name": f"V Street {i}"},
             "geometry": {"type": "LineString", "coordinates": [[X0, Y0 + i * D], [X0 + 2 * D, Y0 + i * D]]}} for i in range(2)]
           + [{"type": "Feature", "properties": {"name": f"V Avenue {i}"},
               "geometry": {"type": "LineString", "coordinates": [[X0 + i * D, Y0], [X0 + i * D, Y0 + D]]}} for i in range(3)])
HP = lambda n: fc([{"type": "Feature", "properties": {"customers": 1},  # noqa: E731
                    "geometry": {"type": "Point", "coordinates": [X0 + 0.0002 + k * 0.0002, Y0 + 0.00008]}} for k in range(n)])


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def db():
    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        await audit.set_actor(session, CALLER)
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def design(db):
    project = (await db.execute(text("SELECT id FROM projects WHERE tenant_id = :t LIMIT 1"), {"t": TENANT})).scalar_one()
    out = await service.create_design(db, TENANT, CALLER, str(project), DesignCreate(name="Versions"))
    d = await service.load_design(db, TENANT, out.id)
    await service.save_inputs(db, TENANT, CALLER, d, "road", "r.geojson", "replace", parse_input_file("road", "r.geojson", ROADS))
    await service.save_inputs(db, TENANT, CALLER, d, "homepass", "h.geojson", "replace", parse_input_file("homepass", "h.geojson", HP(6)))
    return d


async def op(db, design, **body):
    return (await operations.apply_operation(db, TENANT, CALLER, design, body))["operation"]


IDS: dict[str, str] = {}


async def test_every_change_is_audited_with_its_actor(db, design):
    IDS["fdt"] = (await op(db, design, op="ADD_ASSET", asset_type="FDT", lng=X0 + 0.0001, lat=Y0 - 0.00004))["asset_id"]
    IDS["fat"] = (await op(db, design, op="ADD_ASSET", asset_type="FAT", lng=X0 + 0.0008, lat=Y0 + 0.00004))["asset_id"]
    IDS["b2b"] = (await op(db, design, op="DRAW_CABLE", cable_category="BOX_TO_BOX",
                           **{"from": {"asset_id": IDS["fdt"]}, "to": {"asset_id": IDS["fat"]}}))["cable_id"]
    await op(db, design, op="UPDATE_ATTRS", target="asset", id=IDS["fat"], changes={"name": "Corner FAT"})
    await op(db, design, op="MOVE_ASSET", id=IDS["fat"], lng=X0 + 0.0009, lat=Y0 + 0.00004)

    trail = await audit.entity_history(db, TENANT, uuid.UUID(IDS["fat"]))
    actions = [t["action"] for t in reversed(trail)]
    assert actions[0] == "create" and "update" in actions and actions[-1] == "move"
    named = next(t for t in trail if t["action"] == "update" and "name" in t["changed_fields"])
    assert named["old"] == {"name": None} and named["new"] == {"name": "Corner FAT"} and named["actor"] == "versions.tester"
    moved = trail[0]
    assert moved["changed_fields"] == ["geom"] and moved["new"]["geom"]["type"] == "Point"
    whole = await audit.design_history(db, TENANT, design.id)
    assert {t["entity_type"] for t in whole} >= {"asset", "cable", "connection"}


async def test_saved_versions_stay_readable(db, design):
    saved = await versions.save(db, TENANT, CALLER, design, "Hand sketch")
    assert saved["saved"]["version_no"] == 1 and saved["saved"]["frozen"] and saved["saved"]["label"] == "Hand sketch"
    listed = saved["versions"]
    assert [v["version_no"] for v in listed] == [2, 1] and listed[0]["is_current"] and not listed[0]["frozen"]
    assert listed[1]["counts"]["FAT"] == 1 and listed[1]["counts"]["inputs"] == 11

    await op(db, design, op="DELETE_ASSET", id=IDS["fat"])
    IDS["fat2"] = (await op(db, design, op="ADD_ASSET", asset_type="FAT", lng=X0 + 0.0015, lat=Y0 + 0.00004))["asset_id"]
    await op(db, design, op="MOVE_ASSET", id=IDS["fdt"], lng=X0 + 0.0003, lat=Y0 - 0.00004)

    v1 = await versions.version_features(db, TENANT, design, 1)
    codes = {f["properties"]["id"] for f in v1["features"]}
    assert IDS["fat"] in codes and IDS["b2b"] in codes and IDS["fat2"] not in codes
    with pytest.raises(HTTPException):
        await versions.save(db, TENANT, CALLER, design, "  ")


async def test_compare_two_versions(db, design):
    c = await versions.compare(db, TENANT, design, 1, 2)
    assert [f["properties"]["id"] for f in c["added"]] == [IDS["fat2"]]
    # A new FAT never reuses a deleted one's code (the audit trail remembers it)
    assert not {f["properties"]["asset_code"] for f in c["added"]} & {f["properties"]["asset_code"] for f in c["removed"]}
    assert {f["properties"]["id"] for f in c["removed"]} == {IDS["fat"], IDS["b2b"]}
    assert [m["id"] for m in c["moved"]] == [IDS["fdt"]] and 20 < c["moved"][0]["distance_m"] < 25
    with pytest.raises(HTTPException):
        await versions.compare(db, TENANT, design, 2, 2)


async def test_replacing_inputs_keeps_the_old_ones(db, design):
    await service.save_inputs(db, TENANT, CALLER, design, "homepass", "h2.geojson", "replace",
                              parse_input_file("homepass", "h2.geojson", HP(2)))
    listed = await versions.list_versions(db, TENANT, design)
    assert listed[0]["version_no"] == 3 and listed[1]["label"] == "Before replacing homepasses" and listed[1]["frozen"]
    assert (await service.summary(db, TENANT, design))["homepasses"] == 2


async def test_restore_brings_back_the_working_set_and_inputs(db, design):
    before_rows = (await db.execute(text("SELECT count(*) FROM network_audit_log WHERE design_id = :d"), {"d": design.id})).scalar_one()
    r = await versions.restore(db, TENANT, CALLER, design, 1)
    assert r["restored_from"] == 1 and r["kept_as"] == 3 and r["version_no"] == 4 and r["inputs_restored"]
    ids = set((await db.execute(text("SELECT id::text FROM net_assets WHERE design_id = :d"), {"d": design.id})).scalars())
    assert ids == {IDS["fdt"], IDS["fat"]}                                       # same rows, same ids
    assert (await service.summary(db, TENANT, design))["homepasses"] == 6       # the inputs came back too
    fat = (await db.execute(text("SELECT name, ST_X(geom) FROM net_assets WHERE id = :id"), {"id": uuid.UUID(IDS["fat"])})).one()
    assert fat[0] == "Corner FAT" and abs(fat[1] - (X0 + 0.0009)) < 1e-9
    assert (await operations.history(db, TENANT, design))["can_undo"] is False   # a new version, a new edit log

    # One summary row, not one per restored row
    after_rows = (await db.execute(text("SELECT count(*) FROM network_audit_log WHERE design_id = :d"), {"d": design.id})).scalar_one()
    assert after_rows == before_rows + 1
    listed = await versions.list_versions(db, TENANT, design)
    assert listed[0]["creation_method"] == "RESTORED" and listed[1]["label"] == "Before restoring version 1"

    # ...and the state it replaced (version 3) can be restored in turn
    r = await versions.restore(db, TENANT, CALLER, design, 3)
    assert (await service.summary(db, TENANT, design))["homepasses"] == 2
    assert set((await db.execute(text("SELECT id::text FROM net_assets WHERE design_id = :d"), {"d": design.id})).scalars()) \
        == {IDS["fdt"], IDS["fat2"]}


async def test_restore_refusals(db, design):
    cur = (await versions.list_versions(db, TENANT, design))[0]["version_no"]
    with pytest.raises(HTTPException) as exc:
        await versions.restore(db, TENANT, CALLER, design, cur)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        await versions.restore(db, TENANT, CALLER, design, 99)
    assert exc.value.status_code == 404
    await db.execute(text("UPDATE designs SET status = 'APPROVED' WHERE id = :d"), {"d": design.id})
    await db.refresh(design)
    try:
        with pytest.raises(HTTPException) as exc:
            await versions.restore(db, TENANT, CALLER, design, 1)
        assert exc.value.status_code == 409
    finally:
        await db.execute(text("UPDATE designs SET status = 'MODIFIED' WHERE id = :d"), {"d": design.id})
        await db.refresh(design)
