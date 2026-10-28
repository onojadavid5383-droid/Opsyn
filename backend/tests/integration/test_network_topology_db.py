# ============================================================
# OPSYN — tests/integration/test_network_topology_db.py
# Network GIS Phase 3 against real PostGIS (migration 0089):
#
#   - migration-derived connections from the uploaded splitter links
#   - cable endpoints → connection, following edits and deletion
#   - FAT parent_fdt_code → FDT connection
#   - trace upstream to the OLT (path, root, length) and downstream
#     (counts, customers), tenant isolation
#   - manual connections: duplicate 409, loop 422, derived delete 409
#   - utilisation from every basis, and util_pct in the tiles
#   - fibres: TIA-598 listing and recorded status
#
# Same harness as the other DB tests: NETWORK_GIS_DB_URL, one
# transaction rolled back at the end.
# ============================================================

import math
import os
import types
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

if os.environ.get("NETWORK_GIS_DB_URL"):
    import main  # noqa: F401 — registers every ORM mapper, as the app does

from app.modules.gis import tiles
from app.modules.network import cable_service, service, topology_service
from app.modules.network.schemas import (
    AssetCreate, AssetUpdate, CableCreate, CableUpdate, ConnectionCreate,
)

DB_URL = os.environ.get("NETWORK_GIS_DB_URL")
pytestmark = [
    pytest.mark.skipif(not DB_URL, reason="NETWORK_GIS_DB_URL not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

TENANT_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
TENANT_B = uuid.UUID("00000000-0000-0000-0000-0000000000b4")
CALLER = types.SimpleNamespace(id=uuid.UUID("00000000-0000-0000-0000-000000000002"), username="t", staff_profile=None)


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def db():
    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        await session.execute(text("""
            INSERT INTO tenants (id, name, slug) VALUES (:b, 'Topology test tenant B', 'topo-test-b')
            ON CONFLICT (id) DO NOTHING
        """), {"b": TENANT_B})
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
    await engine.dispose()


async def asset_id(db, code) -> str:
    return str((await db.execute(text(
        "SELECT id FROM net_assets WHERE asset_code = :c AND tenant_id = :t AND deleted_at IS NULL"),
        {"c": code, "t": TENANT_A})).scalar_one())


async def links(db, code) -> dict:
    c = await topology_service.list_connections(db, TENANT_A, await asset_id(db, code))
    return {"up": [(x.peer.asset_code, x.connection_type, x.derived_from) for x in c.upstream],
            "down": [(x.peer.asset_code, x.connection_type, x.derived_from) for x in c.downstream]}


def point(lng, lat):
    return {"type": "Point", "coordinates": [lng, lat]}


# ── Derived connections ──────────────────────────────────────

async def test_migration_derived_the_uploaded_splitter_links(db):
    assert (await links(db, "SPL-ALN-02"))["up"] == [("SPL-ALN-01", "SPLIT", "attr:parent_splitter")]
    assert (await links(db, "SPL-ALN-01"))["up"] == [("CAB-ALN-01", "PATCH", "attr:cabinet")]
    # the second-level splitter is fed by its parent, not also by the cabinet
    assert ("SPL-ALN-02", "PATCH", "attr:cabinet") not in (await links(db, "CAB-ALN-01"))["down"]


async def test_cable_endpoints_become_a_connection_that_follows_edits(db):
    olt, cab, cab2 = await asset_id(db, "OLT-IKJ-01"), await asset_id(db, "CAB-ALN-01"), await asset_id(db, "CAB-TOY-02")
    feeder = await cable_service.create_cable(db, TENANT_A, CALLER, CableCreate(
        asset_code="FDR-T-01", cable_category="FEEDER", route_method="IMPORTED", lifecycle_status="ACTIVE",
        fiber_count=24, source_asset_id=olt, dest_asset_id=cab,
        geometry={"type": "LineString", "coordinates": [[3.3530, 6.6010], [3.3555, 6.6032]]},
    ))
    assert ("OLT-IKJ-01", "FEED", "net_cables") in (await links(db, "CAB-ALN-01"))["up"]
    await cable_service.update_cable(db, TENANT_A, CALLER, feeder.id, CableUpdate(dest_asset_id=cab2))
    assert ("OLT-IKJ-01", "FEED", "net_cables") in (await links(db, "CAB-TOY-02"))["up"]
    assert ("OLT-IKJ-01", "FEED", "net_cables") not in (await links(db, "CAB-ALN-01"))["up"]
    await cable_service.update_cable(db, TENANT_A, CALLER, feeder.id, CableUpdate(dest_asset_id=cab))
    # a second feeder from the other OLT, deleted again: its connection goes with it
    tmp = await cable_service.create_cable(db, TENANT_A, CALLER, CableCreate(
        cable_category="FEEDER", route_method="IMPORTED", lifecycle_status="ACTIVE",
        source_asset_id=await asset_id(db, "OLT-IKJ-02"), dest_asset_id=cab2,
        geometry={"type": "LineString", "coordinates": [[3.3650, 6.5960], [3.3490, 6.5975]]},
    ))
    await cable_service.delete_cable(db, TENANT_A, CALLER, tmp.id)
    assert ("OLT-IKJ-02", "FEED", "net_cables") not in (await links(db, "CAB-TOY-02"))["up"]


async def test_fat_parent_fdt_code_links_to_the_fdt(db):
    await service.create_asset(db, TENANT_A, CALLER, AssetCreate(
        asset_code="FDT-T-01", asset_type="FDT", lifecycle_status="ACTIVE", capacity=64,
        geometry=point(3.3547, 6.6021)))
    fat = await service.create_asset(db, TENANT_A, CALLER, AssetCreate(
        asset_code="FAT-T-01", asset_type="FAT", lifecycle_status="ACTIVE", capacity=16,
        attributes={"parent_fdt_code": "fdt-t-01"}, geometry=point(3.3538, 6.5992)))
    assert (await links(db, "FAT-T-01"))["up"] == [("FDT-T-01", "FEED", "attr:parent_fdt")]
    await service.update_asset(db, TENANT_A, CALLER, fat.id, AssetUpdate(attributes={}))
    assert (await links(db, "FAT-T-01"))["up"] == []
    await service.update_asset(db, TENANT_A, CALLER, fat.id, AssetUpdate(attributes={"parent_fdt_code": "FDT-T-01"}))


# ── Manual connections ───────────────────────────────────────

async def test_manual_connections_and_their_rules(db):
    cab, fdt, fat = await asset_id(db, "CAB-ALN-01"), await asset_id(db, "FDT-T-01"), await asset_id(db, "FAT-T-01")
    made = await topology_service.create_connection(db, TENANT_A, CALLER, ConnectionCreate(
        source_asset_id=cab, dest_asset_id=fdt, connection_type="SPLICE"))
    assert made.peer.asset_code == "FDT-T-01" and made.derived_from is None

    with pytest.raises(HTTPException) as exc:             # same link twice
        await topology_service.create_connection(db, TENANT_A, CALLER, ConnectionCreate(
            source_asset_id=cab, dest_asset_id=fdt, connection_type="SPLICE"))
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:             # FAT is below the cabinet: a loop
        await topology_service.create_connection(db, TENANT_A, CALLER, ConnectionCreate(
            source_asset_id=fat, dest_asset_id=cab))
    assert exc.value.status_code == 422 and "loop" in exc.value.detail

    derived = (await topology_service.list_connections(db, TENANT_A, fat)).upstream[0]
    with pytest.raises(HTTPException) as exc:
        await topology_service.delete_connection(db, TENANT_A, CALLER, derived.id)
    assert exc.value.status_code == 409 and "parent FDT code" in exc.value.detail


# ── Trace ────────────────────────────────────────────────────

async def test_trace_upstream_reaches_the_olt(db):
    t = await topology_service.trace(db, TENANT_A, await asset_id(db, "SPL-ALN-02"), "upstream")
    codes = {h.asset.id: h.asset.asset_code for h in t.hops}
    assert [codes[i] for i in t.path_ids] == ["SPL-ALN-02", "SPL-ALN-01", "CAB-ALN-01", "OLT-IKJ-01"]
    assert t.reached_root and t.root.asset_code == "OLT-IKJ-01"
    assert 300 < t.path_length_m < 400                    # only the feeder has a cable on this path
    kinds = {f["properties"]["kind"] for f in t.geometry["features"]}
    assert kinds == {"asset", "cable", "link"}           # patch/split links are logical, drawn separately


async def test_trace_from_a_fat_without_a_path_to_an_olt(db):
    t = await topology_service.trace(db, TENANT_A, await asset_id(db, "FAT-T-01"), "upstream")
    codes = {h.asset.id: h.asset.asset_code for h in t.hops}
    # FAT → FDT → (manual splice) CAB-ALN-01 → feeder → OLT
    assert [codes[i] for i in t.path_ids] == ["FAT-T-01", "FDT-T-01", "CAB-ALN-01", "OLT-IKJ-01"]


async def test_trace_downstream_counts_customers(db):
    fat = await asset_id(db, "FAT-T-01")
    for i in range(3):
        await service.create_asset(db, TENANT_A, CALLER, AssetCreate(
            asset_code=f"ONU-T-{i}", asset_type="ONU", lifecycle_status="ACTIVE", geometry=point(3.3539 + i / 1e4, 6.5990)))
        await topology_service.create_connection(db, TENANT_A, CALLER, ConnectionCreate(
            source_asset_id=fat, dest_asset_id=await asset_id(db, f"ONU-T-{i}"), connection_type="DROP"))
    t = await topology_service.trace(db, TENANT_A, await asset_id(db, "OLT-IKJ-01"), "downstream")
    assert t.customers == 3
    assert t.counts_by_type["SPLITTER"] == 2 and t.counts_by_type["FAT"] == 1 and t.counts_by_type["FDT"] == 1
    assert not t.truncated and t.path_ids == []


async def test_trace_is_tenant_isolated(db):
    with pytest.raises(HTTPException) as exc:
        await topology_service.trace(db, TENANT_B, await asset_id(db, "OLT-IKJ-01"), "downstream")
    assert exc.value.status_code == 404


# ── Utilisation ──────────────────────────────────────────────

async def test_utilisation_from_every_basis(db):
    u = lambda code: asset_id(db, code)
    fat = await topology_service.utilisation(db, TENANT_A, await u("FAT-T-01"))
    assert (fat.capacity, fat.used, fat.basis, fat.state, fat.capacity_label) == (16, 3, "connections", "ok", "Customer ports")
    fdt = await topology_service.utilisation(db, TENANT_A, await u("FDT-T-01"))
    assert (fdt.capacity, fdt.used, fdt.basis, fdt.pct) == (64, 16, "fat_ports", 25.0)
    spl = await topology_service.utilisation(db, TENANT_A, await u("SPL-TOY-01"))
    assert (spl.capacity, spl.used, spl.basis) == (8, 3, "recorded")            # the upload's number_customer
    olt_id = await u("OLT-IKJ-01")
    for n in range(4):
        await db.execute(text("""
            INSERT INTO net_ports (tenant_id, asset_id, port_label, port_no, port_type, status)
            VALUES (:t, :a, :l, :n, 'PON', :s)
        """), {"t": TENANT_A, "a": olt_id, "l": f"0/1/{n}", "n": n, "s": "USED" if n < 3 else "FREE"})
    olt = await topology_service.utilisation(db, TENANT_A, olt_id)
    assert (olt.capacity, olt.used, olt.basis, olt.state) == (4, 3, "ports", "warning")
    cab = await topology_service.utilisation(db, TENANT_A, await u("CAB-OPB-03"))
    assert cab.basis == "none" and cab.state == "unknown"


async def test_tiles_carry_utilisation(db):
    from tests.integration.test_network_gis_db import decode_mvt, lnglat_to_tile
    z = 17
    x, y = lnglat_to_tile(3.3538, 6.5992, z)
    raw = (await db.execute(text(tiles.TILE_SQL), tiles.tile_params(TENANT_A, z, x, y))).scalar_one()
    fat = next(f for f in decode_mvt(bytes(raw))["assets"] if f.get("asset_code") == "FAT-T-01")
    # The test reader decodes property names but only string values, so the
    # key is checked here and the number through the same SQL the tile uses
    assert "util_pct" in fat
    pct = (await db.execute(text(f"""
        SELECT CASE WHEN {tiles.UTIL_CAPACITY} > 0 THEN round(100.0 * {tiles.UTIL_USED} / {tiles.UTIL_CAPACITY})::int END
        FROM net_assets a {tiles.UTIL_JOINS} WHERE a.asset_code = 'FAT-T-01'
    """))).scalar_one()
    assert pct == math.floor(100 * 3 / 16 + 0.5)


# ── Fibres ───────────────────────────────────────────────────

async def test_fibres(db):
    cable = (await db.execute(text("SELECT id FROM net_cables WHERE asset_code = 'FDR-T-01'"))).scalar_one()
    fibres = await topology_service.list_fibres(db, TENANT_A, str(cable))
    assert len(fibres) == 24 and fibres[12].tube_colour == "Orange" and fibres[12].colour == "Blue"
    f = await topology_service.set_fibre_status(db, TENANT_A, CALLER, str(cable), 13, "USED")
    assert f.status == "USED" and f.recorded
    with pytest.raises(HTTPException) as exc:
        await topology_service.set_fibre_status(db, TENANT_A, CALLER, str(cable), 25, "USED")
    assert exc.value.status_code == 404


# ── Conflicts undo only themselves ───────────────────────────

async def test_a_rejected_duplicate_keeps_earlier_work(db):
    await service.create_asset(db, TENANT_A, CALLER, AssetCreate(
        asset_code="HH-T-01", asset_type="HANDHOLE", geometry=point(3.3549, 6.6018)))
    with pytest.raises(HTTPException) as exc:
        await service.create_asset(db, TENANT_A, CALLER, AssetCreate(
            asset_code="HH-T-01", asset_type="HANDHOLE", geometry=point(3.3550, 6.6019)))
    assert exc.value.status_code == 409
    assert await asset_id(db, "HH-T-01")                  # the first one is still there
    assert await asset_id(db, "FAT-T-01")                 # and so is everything before it


async def test_a_rejected_code_change_keeps_earlier_work(db):
    hh2 = await service.create_asset(db, TENANT_A, CALLER, AssetCreate(
        asset_code="HH-T-02", asset_type="HANDHOLE", geometry=point(3.3551, 6.6020)))
    with pytest.raises(HTTPException) as exc:
        await service.update_asset(db, TENANT_A, CALLER, hh2.id, AssetUpdate(asset_code="HH-T-01"))
    assert exc.value.status_code == 409
    assert await asset_id(db, "HH-T-01") and await asset_id(db, "FAT-T-01")
