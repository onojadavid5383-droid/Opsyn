# ============================================================
# OPSYN — tests/integration/test_auto_design_db.py
# Network GIS Phase 5 against real PostGIS and the real FTTx engine:
#   generate (queued run, inputs copied, busy / non-empty refusals, broker
#   down) → the engine run exactly as the Celery task runs it → output into
#   the working set as a new AUTO version (rows, connections, BOQ snapshot,
#   engine findings, validation) → features / hydrated BOQ → regenerate
#   (previous state snapshotted) → import an existing run into another
#   design → a design in review refuses the output.
# Celery itself is not started: .delay is replaced, and the task body's
# steps are called directly (the task is a thin wrapper around them).
# Harness as the other DB tests: NETWORK_GIS_DB_URL, rolled back at the end.
# ============================================================

import gzip
import json
import os
import types
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

if os.environ.get("NETWORK_GIS_DB_URL"):
    import main  # noqa: F401 — registers every ORM mapper

from app.modules.design import auto_design, boq_service, service
from app.modules.design.inputs import parse_input_file
from app.modules.design.models import DesignVersion
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

# A 3x3 block grid (~110 m blocks) with homepasses every ~20 m along both
# sides of the four east-west streets — dense enough for the engine's drop
# and box-to-box limits (a sparse layout is refused by the engine's gates)
X0, Y0, D = 3.3700, 6.6100, 0.001


def fc(features):
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


ROADS = fc([
    *({"type": "Feature", "properties": {"name": f"Test Street {i}"},
       "geometry": {"type": "LineString", "coordinates": [[X0, Y0 + i * D], [X0 + 3 * D, Y0 + i * D]]}} for i in range(4)),
    *({"type": "Feature", "properties": {"name": f"Test Avenue {i}"},
       "geometry": {"type": "LineString", "coordinates": [[X0 + i * D, Y0], [X0 + i * D, Y0 + 3 * D]]}} for i in range(4)),
])
HP = [{"type": "Feature", "properties": {"Customers": 2 if k % 5 == 0 else 1},
       "geometry": {"type": "Point", "coordinates": [X0 + 0.00012 + k * 0.00018, Y0 + i * D + side * 0.00009]}}
      for i in range(4) for side in (-1, 1) if not (i == 0 and side < 0) and not (i == 3 and side > 0) for k in range(16)]
CUSTOMERS = sum(f["properties"]["Customers"] for f in HP)
FAR_HP = {"type": "Feature", "properties": {"Customers": 1}, "geometry": {"type": "Point", "coordinates": [X0 + 0.02, Y0 + 0.02]}}


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


async def new_design(db, name, with_inputs=True):
    project = (await db.execute(text("SELECT id FROM projects WHERE tenant_id = :t LIMIT 1"), {"t": TENANT})).scalar_one()
    out = await service.create_design(db, TENANT, CALLER, str(project), DesignCreate(name=name))
    d = await service.load_design(db, TENANT, out.id)
    if with_inputs:
        await service.save_inputs(db, TENANT, CALLER, d, "road", "roads.geojson", "replace",
                                  parse_input_file("road", "roads.geojson", ROADS))
        await service.save_inputs(db, TENANT, CALLER, d, "homepass", "hp.geojson", "replace",
                                  parse_input_file("homepass", "hp.geojson", fc(HP)))
        await service.boundary_from_inputs(db, TENANT, CALLER, out.id)
        await service.save_inputs(db, TENANT, CALLER, d, "homepass", "far.geojson", "append",
                                  parse_input_file("homepass", "far.geojson", fc([FAR_HP])))
    return await service.load_design(db, TENANT, out.id)


async def run_like_the_task(db, run: FttxDesignRun) -> FttxDesignRunOutput:
    """The task body (app/tasks/fttx_design_run.py): layers → engine → stored output."""
    layers = {r.layer_key: r.geojson for r in (await db.execute(
        select(FttxDesignRunLayer).where(FttxDesignRunLayer.run_id == run.id))).scalars().all()}
    engine_layers, _crs = build_input_layers(layers)
    result = run_fttx_design(config=config_from_dict(run.config), layers=engine_layers)
    output = FttxDesignRunOutput(
        run_id=run.id, tenant_id=run.tenant_id,
        output_layers={k: layer_to_geojson(v) for k, v in result.output_layers.items()},
        boq_rows=layer_to_rows(result.output_layers["boq"]), boq_fdt_rows=layer_to_rows(result.output_layers["boq_fdt"]),
        optical_loss_summary=result.optical_loss_summary,
    )
    db.add(output)
    run.status = "completed"
    await db.flush()
    return output


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def design(db):
    return await new_design(db, "Auto design test")


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def live_pole(db):
    """A pole already in service beside Test Street 1, which the engine should reuse."""
    pid = (await db.execute(text("""
        INSERT INTO net_assets (tenant_id, asset_code, asset_type, geom, lifecycle_status, creation_method, attributes)
        VALUES (:t, 'POLE-AUTO-LIVE', 'POLE', ST_SetSRID(ST_MakePoint(:x, :y), 4326), 'ACTIVE', 'MANUAL', '{}')
        RETURNING id
    """), {"t": TENANT, "x": X0 + 0.0015, "y": Y0 + D + 0.00002})).scalar_one()
    return pid


def fake_delay(monkeypatch, fail=False):
    from app.tasks import fttx_design_run

    def delay(run_id):
        if fail:
            raise ConnectionError("broker down")
        return types.SimpleNamespace(id=f"task-{run_id}")
    monkeypatch.setattr(fttx_design_run.run_fttx_design_task, "delay", delay)


# ── Generate ─────────────────────────────────────────────────

async def test_generate_queues_a_run_from_the_design_inputs(db, design, live_pole, monkeypatch):
    fake_delay(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await auto_design.queue_generate(db, TENANT, CALLER, design, {"deployment_type": "underground"}, False)
    assert exc.value.status_code == 422

    out = await auto_design.queue_generate(db, TENANT, CALLER, design, {"coverage_pct": 100}, False)
    assert out["status"] == "queued" and out["progress_message"] == "Queued"
    assert "1 homepass outside the boundary was left out" in out["notes"]
    assert "1 pole already in the network was offered to the engine as existing structures" in out["notes"]
    run = await db.get(FttxDesignRun, uuid.UUID(out["run_id"]))
    assert run.design_id == design.id and run.celery_task_id == f"task-{run.id}"
    assert run.config["homepass_field_name"] == "customers" and design.engine_config == {"coverage_pct": 100}
    layers = {r.layer_key: r.feature_count for r in (await db.execute(
        select(FttxDesignRunLayer).where(FttxDesignRunLayer.run_id == run.id))).scalars().all()}
    assert layers == {"road": 8, "homepass": len(HP), "pole": 1}

    with pytest.raises(HTTPException) as exc:                        # one run at a time
        await auto_design.queue_generate(db, TENANT, CALLER, design, None, False)
    assert exc.value.status_code == 409 and "already running" in exc.value.detail


async def test_the_run_becomes_a_new_auto_version(db, design):
    run = await auto_design.latest_run(db, TENANT, design.id)
    output = await run_like_the_task(db, run)
    pole_fc = next(r.geojson for r in (await db.execute(
        select(FttxDesignRunLayer).where(FttxDesignRunLayer.run_id == run.id))).scalars().all() if r.layer_key == "pole")
    res = await auto_design.apply_output(db, TENANT, design.id, output=output, run=run, pole_fc=pole_fc,
                                         method="AUTO", label="Auto design")
    counts = res["counts"]
    assert res["version_no"] == 2 and counts["FDT"] >= 2 and counts["FAT"] == counts["SPLITTER"] >= 14
    assert counts["DROP"] == CUSTOMERS and counts["BOX_TO_BOX"] >= counts["FAT"]

    d = await service.load_design(db, TENANT, design.id)
    v = await db.get(DesignVersion, d.current_version_id)
    assert d.status == "GENERATED" and v.creation_method == "AUTO" and v.parent_version_id is not None
    assert v.boq_snapshot["streets"] and v.boq_snapshot["fdt_detail"]
    assert "validated_at" in v.validation_summary and isinstance(v.validation_summary["engine_findings"], list)
    assert run.design_version_id == v.id

    # The live pole came back as an existing pole of the design
    pole = (await db.execute(text("""
        SELECT attributes FROM net_assets WHERE design_id = :d AND asset_type = 'POLE' AND attributes->>'live_asset_code' = 'POLE-AUTO-LIVE'
    """), {"d": design.id})).scalar_one_or_none()
    assert pole is not None and pole["existing"] is True

    # Every FAT is fed; drops go straight to the premises and are not flagged
    issues = await auto_design.validation_service.stored_issues(db, TENANT, design.id)
    bad = [i["message"] for i in issues
           if i["code"] in ("FAT_NOT_FED", "FAT_OVER_CAPACITY", "CABLE_UNLINKED", "HAND_DRAWN_ROUTE", "EMPTY_DESIGN")]
    assert not bad, bad
    direct = (await db.execute(text("SELECT count(*) FROM net_cables WHERE design_id = :d AND route_method = 'DIRECT'"),
                               {"d": design.id})).scalar_one()
    assert direct == CUSTOMERS


async def test_the_generated_design_reads_back(db, design):
    d = await service.load_design(db, TENANT, design.id)
    summary = await service.summary(db, TENANT, d)
    assert summary["fat"] >= 14 and summary["splitters"] == summary["fat"] and summary["cable_km"] > 1
    feats = await service.working_set_features(db, TENANT, d)
    assets, cables = await auto_design.working_set_size(db, d.id)
    kinds = [f["properties"]["kind"] for f in feats["features"]]
    assert (kinds.count("asset"), kinds.count("cable")) == (assets, cables)
    # The hydrator reads the engine's own rows back: the street BOQ runs on them
    boq = await boq_service.compute_boq(db, TENANT, d)
    q = {x["code"]: x["quantity"] for x in boq["quantities"] if x["group"] == "Devices"}
    assert q["FAT"] == summary["fat"] and boq["street_boq_available"]
    assert sum(r.get("total_fat") or 0 for r in boq["streets"] if r.get("level_type") != "ALL"
               and r.get("street_name") not in (None, "", "ALL")) >= summary["fat"] - 2


async def test_regenerate_needs_confirmation_and_keeps_the_old_state(db, design, monkeypatch):
    fake_delay(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await auto_design.queue_generate(db, TENANT, CALLER, design, None, False)
    assert exc.value.status_code == 409 and "Confirm to replace" in exc.value.detail
    out = await auto_design.queue_generate(db, TENANT, CALLER, design, None, True)
    run = await db.get(FttxDesignRun, uuid.UUID(out["run_id"]))
    output = await run_like_the_task(db, run)
    res = await auto_design.apply_output(db, TENANT, design.id, output=output, run=run, pole_fc=None,
                                         method="AUTO", label="Auto design")
    assert res["version_no"] == 3
    v2 = (await db.execute(select(DesignVersion).where(DesignVersion.design_id == design.id,
                                                        DesignVersion.version_no == 2))).scalar_one()
    snap = json.loads(gzip.decompress(v2.snapshot))
    assert snap["format"] == 2 and len(snap["assets"]) > 0 and len(snap["cables"]) >= CUSTOMERS
    status = await auto_design.run_status(db, TENANT, await service.load_design(db, TENANT, design.id))
    assert status["status"] == "completed" and status["design_version"]["version_no"] == 3


async def test_broker_down_fails_the_run_cleanly(db, monkeypatch):
    other = await new_design(db, "Broker test")
    fake_delay(monkeypatch, fail=True)
    with pytest.raises(HTTPException) as exc:
        await auto_design.queue_generate(db, TENANT, CALLER, other, None, False)
    assert exc.value.status_code == 503
    status = await auto_design.run_status(db, TENANT, other)
    assert status["status"] == "failed" and "task queue is unavailable" in status["error_message"]


# ── Import an existing run ───────────────────────────────────

async def test_import_a_standalone_run(db, design):
    # A run made in the standalone FTTx Designer: no design, its own settings
    source = await auto_design.latest_run(db, TENANT, design.id)
    layers = (await db.execute(select(FttxDesignRunLayer).where(FttxDesignRunLayer.run_id == source.id))).scalars().all()
    run = FttxDesignRun(tenant_id=TENANT, name="Kokona phase 1", status="draft",
                        config={"homepass_field_name": "customers", "coverage_pct": 100, "pon_architecture": "single_pon"})
    db.add(run)
    await db.flush()
    for r in layers:
        db.add(FttxDesignRunLayer(run_id=run.id, tenant_id=TENANT, layer_key=r.layer_key, geojson=r.geojson,
                                  feature_count=r.feature_count))
    await db.flush()
    await run_like_the_task(db, run)

    target = await new_design(db, "Imported", with_inputs=False)
    listed = await auto_design.importable_runs(db, TENANT, target)
    assert any(x["id"] == str(run.id) and not x["from_this_design"] for x in listed)
    res = await auto_design.import_run(db, TENANT, CALLER, target, str(run.id), False)
    assert res["version_no"] == 2 and set(res["inputs_copied"]) >= {"road", "homepass"}
    t = await service.load_design(db, TENANT, target.id)
    v = await db.get(DesignVersion, t.current_version_id)
    assert v.creation_method == "IMPORTED" and "Kokona phase 1" in v.label
    assert t.engine_config == {"coverage_pct": 100, "pon_architecture": "single_pon"}
    assert (await service.summary(db, TENANT, t))["homepasses"] == len(HP)

    with pytest.raises(HTTPException) as exc:                         # not twice without confirming
        await auto_design.import_run(db, TENANT, CALLER, t, str(run.id), False)
    assert exc.value.status_code == 409


async def test_a_design_in_review_refuses_the_output(db, design):
    run = await auto_design.latest_run(db, TENANT, design.id)
    output = (await db.execute(select(FttxDesignRunOutput).where(FttxDesignRunOutput.run_id == run.id))).scalar_one()
    await db.execute(text("UPDATE designs SET status = 'UNDER_REVIEW' WHERE id = :d"), {"d": design.id})
    try:
        with pytest.raises(auto_design.DesignLocked):
            await auto_design.apply_output(db, TENANT, design.id, output=output, run=run, pole_fc=None,
                                           method="AUTO", label="late")
    finally:
        await db.execute(text("UPDATE designs SET status = 'GENERATED' WHERE id = :d"), {"d": design.id})
