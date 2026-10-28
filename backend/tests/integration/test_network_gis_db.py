# ============================================================
# OPSYN — tests/integration/test_network_gis_db.py
# Network GIS Phase 1 against a real PostGIS database at migration 0087:
#
#   - MVT tiles: both source-layers, zoom bands, contained assets,
#     live-only filtering, tenant isolation
#   - net_cables.length_m trigger
#   - backfill idempotency and soft-delete mirroring
#   - network revision moves on every write
#   - search ranking
#
# Needs NETWORK_GIS_DB_URL (an asyncpg URL of a database migrated to
# 0087 that has the seed rows in tests/integration/network_gis_seed.sql);
# skipped otherwise. Everything runs in one transaction that is rolled
# back, so the database is left as it was.
#
#   NETWORK_GIS_DB_URL=postgresql+asyncpg://opsyn:…@localhost:5432/opsyn_gis_test \
#     pytest tests/integration/test_network_gis_db.py
# ============================================================

import math
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.gis import tiles
from app.modules.network.backfill import BACKFILL_STATEMENTS, COUNT_SQL
from app.modules.network.service import search_assets

DB_URL = os.environ.get("NETWORK_GIS_DB_URL")
pytestmark = [
    pytest.mark.skipif(not DB_URL, reason="NETWORK_GIS_DB_URL not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

TENANT_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
TENANT_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")

# Seeded OLT-IKJ-01 (3.3530, 6.6010) and SPL-ALN-02 (3.3572, 6.6051)
OLT_LNG, OLT_LAT = 3.3530, 6.6010
SPL2_LNG, SPL2_LAT = 3.3572, 6.6051


# ── Minimal MVT (protobuf) reader: layer names → feature id/code ─────

def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def _fields(buf: bytes):
    """Yield (field_no, wire_type, value) for one protobuf message."""
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            val, i = _varint(buf, i)
        elif wire == 2:
            n, i = _varint(buf, i)
            val, i = buf[i:i + n], i + n
        elif wire == 5:
            val, i = buf[i:i + 4], i + 4
        elif wire == 1:
            val, i = buf[i:i + 8], i + 8
        else:  # pragma: no cover
            raise ValueError(f"unsupported wire type {wire}")
        yield field, wire, val


def decode_mvt(data: bytes) -> dict[str, list[dict[str, str]]]:
    """{layer name: [ {prop: value (strings only)} per feature ]}."""
    out: dict[str, list[dict[str, str]]] = {}
    for field, _w, layer in _fields(data):
        if field != 3:
            continue
        name, keys, values, features = "", [], [], []
        for f, _w2, v in _fields(layer):
            if f == 1:
                name = v.decode()
            elif f == 3:
                keys.append(v.decode())
            elif f == 4:
                sval = None
                for vf, _vw, vv in _fields(v):
                    if vf == 1:
                        sval = vv.decode()
                values.append(sval)
            elif f == 2:
                features.append(v)
        rows = []
        for feat in features:
            tags: list[int] = []
            for ff, fw, fv in _fields(feat):
                if ff == 2 and fw == 2:  # packed tags
                    j = 0
                    while j < len(fv):
                        t, j = _varint(fv, j)
                        tags.append(t)
            rows.append({keys[tags[k]]: values[tags[k + 1]] for k in range(0, len(tags), 2)})
        out[name] = rows
    return out


def lnglat_to_tile(lng: float, lat: float, z: int) -> tuple[int, int]:
    n = 1 << z
    x = int((lng + 180) / 360 * n)
    lat_r = math.radians(lat)
    y = int((1 - math.asinh(math.tan(lat_r)) / math.pi) / 2 * n)
    return x, y


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def db():
    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn)
        await session.execute(text("""
            INSERT INTO tenants (id, name, slug) VALUES (:b, 'GIS test tenant B', 'gis-test-b')
            ON CONFLICT (id) DO NOTHING
        """), {"b": TENANT_B})
        # Tenant B owns an OLT at the same spot as tenant A's.
        await session.execute(text("""
            INSERT INTO net_assets (tenant_id, asset_code, asset_type, geom, lifecycle_status, creation_method)
            VALUES (:b, 'OLT-OTHER-TENANT', 'OLT', ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), 'ACTIVE', 'MANUAL')
        """), {"b": TENANT_B, "lng": OLT_LNG, "lat": OLT_LAT})
        # A planned (not live) asset and a feeder cable for tenant A.
        await session.execute(text("""
            INSERT INTO net_assets (tenant_id, asset_code, asset_type, geom, lifecycle_status, creation_method)
            VALUES (:a, 'FDT-PLANNED-1', 'FDT', ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), 'PLANNED', 'MANUAL')
        """), {"a": TENANT_A, "lng": OLT_LNG + 0.0004, "lat": OLT_LAT})
        await session.execute(text("""
            INSERT INTO net_cables (tenant_id, asset_code, cable_category, geom, lifecycle_status, creation_method, fiber_count)
            VALUES (:a, 'FDR-IKJ-01', 'FEEDER',
                    ST_SetSRID(ST_MakeLine(ST_MakePoint(3.3530, 6.6010), ST_MakePoint(3.3555, 6.6032)), 4326),
                    'ACTIVE', 'MANUAL', 48)
        """), {"a": TENANT_A})
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
    await engine.dispose()


async def _tile(db, tenant, lng, lat, z):
    x, y = lnglat_to_tile(lng, lat, z)
    data = (await db.execute(text(tiles.TILE_SQL), tiles.tile_params(tenant, z, x, y))).scalar_one()
    return decode_mvt(bytes(data or b""))


def _codes(tile, layer):
    return {f.get("asset_code") for f in tile.get(layer, [])}


# ── Tiles ────────────────────────────────────────────────────────────

async def test_tile_carries_both_source_layers(db):
    tile = await _tile(db, TENANT_A, OLT_LNG, OLT_LAT, 15)
    assert "OLT-IKJ-01" in _codes(tile, "assets")
    assert "FDR-IKJ-01" in _codes(tile, "cables")
    feat = next(f for f in tile["assets"] if f["asset_code"] == "OLT-IKJ-01")
    assert feat["asset_type"] == "OLT" and feat["lifecycle_status"] == "ACTIVE"
    uuid.UUID(feat["id"])  # string UUID the inspector can fetch


async def test_tile_is_tenant_isolated(db):
    assert "OLT-OTHER-TENANT" not in _codes(await _tile(db, TENANT_A, OLT_LNG, OLT_LAT, 15), "assets")
    tile_b = await _tile(db, TENANT_B, OLT_LNG, OLT_LAT, 15)
    assert _codes(tile_b, "assets") == {"OLT-OTHER-TENANT"}
    assert "cables" not in tile_b


async def test_tile_shows_only_live_states(db):
    assert "FDT-PLANNED-1" not in _codes(await _tile(db, TENANT_A, OLT_LNG, OLT_LAT, 15), "assets")


async def test_zoom_bands(db):
    low = await _tile(db, TENANT_A, OLT_LNG, OLT_LAT, 10)
    assert "OLT-IKJ-01" in _codes(low, "assets")
    assert not any(c.startswith("SPL-") for c in _codes(low, "assets"))
    assert "FDR-IKJ-01" in _codes(low, "cables")
    street = await _tile(db, TENANT_A, SPL2_LNG, SPL2_LAT, 14)
    assert "SPL-ALN-02" in _codes(street, "assets")


async def test_contained_assets_wait_for_close_zoom(db):
    await db.execute(text("""
        UPDATE net_assets SET parent_id = (SELECT id FROM net_assets WHERE asset_code = 'CAB-ALN-01' AND tenant_id = :a)
        WHERE asset_code = 'SPL-ALN-02' AND tenant_id = :a
    """), {"a": TENANT_A})
    assert "SPL-ALN-02" not in _codes(await _tile(db, TENANT_A, SPL2_LNG, SPL2_LAT, 16), "assets")
    close = await _tile(db, TENANT_A, SPL2_LNG, SPL2_LAT, 18)
    feat = next(f for f in close["assets"] if f["asset_code"] == "SPL-ALN-02")
    assert feat is not None
    await db.execute(text("UPDATE net_assets SET parent_id = NULL WHERE asset_code = 'SPL-ALN-02'"))


async def test_empty_tile_is_empty_bytes(db):
    x, y = lnglat_to_tile(-120.0, 45.0, 12)
    data = (await db.execute(text(tiles.TILE_SQL), tiles.tile_params(TENANT_A, 12, x, y))).scalar_one()
    assert bytes(data or b"") == b""


# ── Cables ───────────────────────────────────────────────────────────

async def test_cable_length_comes_from_geometry(db):
    length, expected = (await db.execute(text("""
        SELECT length_m, round(ST_Length(geom::geography)::numeric, 2)
        FROM net_cables WHERE asset_code = 'FDR-IKJ-01' AND tenant_id = :a
    """), {"a": TENANT_A})).one()
    assert length == expected and 300 < float(length) < 400
    await db.execute(text("""
        UPDATE net_cables SET geom = ST_SetSRID(ST_MakeLine(ST_MakePoint(3.3530, 6.6010), ST_MakePoint(3.3530, 6.6020)), 4326),
                              length_m = 1
        WHERE asset_code = 'FDR-IKJ-01' AND tenant_id = :a
    """), {"a": TENANT_A})
    length = (await db.execute(text("SELECT length_m FROM net_cables WHERE asset_code = 'FDR-IKJ-01'"))).scalar_one()
    assert 105 < float(length) < 115  # ~0.001° of latitude, never the client's value


# ── Backfill ─────────────────────────────────────────────────────────

async def _counts(db):
    rows = (await db.execute(text(COUNT_SQL), {"tid": str(TENANT_A)})).all()
    return {r.source_table: r.n for r in rows}


async def test_backfill_is_idempotent(db):
    before = await _counts(db)
    assert before == {"olts": 2, "cabinets": 3, "splitter_boxes": 4}
    for _ in range(2):
        for stmt in BACKFILL_STATEMENTS:
            await db.execute(text(stmt), {"tid": str(TENANT_A)})
    assert await _counts(db) == before


async def test_backfill_mirrors_source_soft_delete_and_edits(db):
    await db.execute(text("UPDATE splitter_boxes SET is_deleted = true WHERE box_id = 'SPL-TOY-01'"))
    await db.execute(text("UPDATE olts SET location_description = 'Moved desk' WHERE name = 'OLT-IKJ-02'"))
    for stmt in BACKFILL_STATEMENTS:
        await db.execute(text(stmt), {"tid": str(TENANT_A)})
    deleted = (await db.execute(text(
        "SELECT deleted_at IS NOT NULL FROM net_assets WHERE asset_code = 'SPL-TOY-01'"))).scalar_one()
    desc = (await db.execute(text(
        "SELECT description FROM net_assets WHERE asset_code = 'OLT-IKJ-02' AND deleted_at IS NULL"))).scalar_one()
    assert deleted and desc == "Moved desk"
    assert (await _counts(db))["splitter_boxes"] == 3


# ── Revision & search ────────────────────────────────────────────────

async def test_revision_moves_on_write(db):
    rev = lambda: db.execute(text(tiles.REVISION_SQL), {"tid": TENANT_A})
    before = (await rev()).scalar_one()
    assert tiles.valid_revision(before)
    await db.execute(text("UPDATE net_assets SET name = 'renamed', updated_at = now() + interval '1 second' "
                          "WHERE asset_code = 'OLT-IKJ-01'"))
    assert (await rev()).scalar_one() != before


async def test_search_ranks_exact_code_first_and_skips_non_live(db):
    results = await search_assets(db, TENANT_A, "SPL-ALN-01")
    assert results[0].asset_code == "SPL-ALN-01"
    codes = [r.asset_code for r in await search_assets(db, TENANT_A, "ALN")]
    assert "CAB-ALN-01" in codes and "SPL-ALN-01" in codes
    assert not await search_assets(db, TENANT_A, "FDT-PLANNED")          # not live
    assert not await search_assets(db, TENANT_A, "OLT-OTHER")            # other tenant
    only_cab = await search_assets(db, TENANT_A, "ALN", asset_type="CABINET")
    assert {r.asset_type for r in only_cab} == {"CABINET"}
