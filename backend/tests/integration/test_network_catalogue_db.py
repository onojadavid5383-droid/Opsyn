# ============================================================
# OPSYN — tests/integration/test_network_catalogue_db.py
# Network GIS Phase 2 against real PostGIS (migration 0088):
#
#   - generated codes: sequence per tenant + prefix, never reused
#   - network uploads through the real upload service (validate → commit):
#     poles from Excel, cables from GeoJSON with endpoint resolution
#   - dual-write: legacy OLT upload and bulk deletion keep net_assets in step
#   - asset / cable services: generated code, attribute validation,
#     line edit → MANUAL_GEOMETRY + recomputed length, lifecycle rules
#
# Same harness as test_network_gis_db.py: NETWORK_GIS_DB_URL, one
# transaction rolled back at the end.
# ============================================================

import io
import json
import os
import types
import uuid

import openpyxl
import pytest
import pytest_asyncio

if os.environ.get("NETWORK_GIS_DB_URL"):
    # Registers every ORM mapper (Task → Department, …) the way the app does;
    # only when these tests will actually run, since it needs the app's env.
    import main  # noqa: F401
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.infrastructure.deletion_service import execute_deletion
from app.modules.infrastructure.models import InfraDeletionSession, InfraUploadSession
from app.modules.infrastructure.upload_service import commit_session, run_full_validation
from app.modules.network import cable_service, service
from app.modules.network.codes import next_codes
from app.modules.network.schemas import AssetCreate, AssetUpdate, CableCreate, CableUpdate

DB_URL = os.environ.get("NETWORK_GIS_DB_URL")
pytestmark = [
    pytest.mark.skipif(not DB_URL, reason="NETWORK_GIS_DB_URL not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

TENANT_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
TENANT_B = uuid.UUID("00000000-0000-0000-0000-0000000000b3")
ADMIN = uuid.UUID("00000000-0000-0000-0000-000000000002")
CALLER = types.SimpleNamespace(id=ADMIN, username="david.onoja", staff_profile=None)


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def db():
    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        await session.execute(text("""
            INSERT INTO tenants (id, name, slug) VALUES (:b, 'Catalogue test tenant B', 'cat-test-b')
            ON CONFLICT (id) DO NOTHING
        """), {"b": TENANT_B})
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
    await engine.dispose()


def xlsx(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def upload(db, asset_type: str, filename: str, data: bytes):
    s = InfraUploadSession(tenant_id=TENANT_A, asset_type=asset_type, status="pending",
                           original_filename=filename, submitted_by=ADMIN)
    db.add(s)
    await db.flush()
    summary = await run_full_validation(db, s.id, asset_type, data, TENANT_A, filename)
    return s, summary


async def _insert_asset(db, tenant, code, type_="FAT"):
    await db.execute(text("""
        INSERT INTO net_assets (tenant_id, asset_code, asset_type, geom, lifecycle_status, creation_method)
        VALUES (:t, :c, :ty, ST_SetSRID(ST_MakePoint(3.35, 6.6), 4326), 'ACTIVE', 'MANUAL')
    """), {"t": tenant, "c": code, "ty": type_})


# ── Codes ────────────────────────────────────────────────────

async def test_codes_continue_the_tenant_sequence(db):
    await _insert_asset(db, TENANT_A, "FAT-0041")
    await _insert_asset(db, TENANT_A, "FAT-9X")            # hand-typed: ignored by the sequence
    await _insert_asset(db, TENANT_B, "FAT-0500")          # other tenant: ignored
    assert await next_codes(db, TENANT_A, "asset", "FAT", 3) == ["FAT-0042", "FAT-0043", "FAT-0044"]
    await db.execute(text("UPDATE net_assets SET deleted_at = now() WHERE asset_code = 'FAT-0041' AND tenant_id = :t"),
                     {"t": TENANT_A})
    # a retired code is never handed out again
    assert (await next_codes(db, TENANT_A, "asset", "FAT"))[0] == "FAT-0042"
    assert (await next_codes(db, TENANT_B, "asset", "FAT"))[0] == "FAT-0501"


# ── Network uploads ──────────────────────────────────────────

async def test_pole_upload_validates_commits_and_dedupes(db):
    data = xlsx([
        ["asset_code", "longitude", "latitude", "height_m", "material", "ownership"],
        ["POLE-7000", 3.3541, 6.6003, 9, "concrete", "leased"],
        [None, 3.3551, 6.6000, "11", "steel", None],
        [None, 3.3561, 6.5997, 10, "bamboo", None],        # bad material
        ["POLE-7000", 3.3571, 6.5994, 9, None, None],      # same code twice in the file
    ])
    s, summary = await upload(db, "pole", "poles.xlsx", data)
    assert summary.status == "validated"
    assert (summary.total_rows, summary.valid_rows, summary.error_rows) == (4, 2, 2)
    assert {e["field"] for e in summary.errors} == {"material", "asset_code"}

    result = await commit_session(db, s.id, TENANT_A, ADMIN)
    assert result.status == "committed" and result.committed_rows == 2
    rows = (await db.execute(text("""
        SELECT asset_code, creation_method, lifecycle_status, source_table, attributes
        FROM net_assets WHERE source_table = 'infrastructure_upload_staging' AND asset_type = 'POLE'
        ORDER BY asset_code
    """))).all()
    codes = [r.asset_code for r in rows]
    assert "POLE-7000" in codes and any(c.startswith("POLE-") and c != "POLE-7000" for c in codes)
    assert all(r.creation_method == "IMPORTED" and r.lifecycle_status == "ACTIVE" for r in rows)
    assert next(r for r in rows if r.asset_code == "POLE-7000").attributes == {
        "height_m": 9.0, "material": "CONCRETE", "ownership": "LEASED"}

    # Uploading the coded pole again: a duplicate, not a second row
    _s2, again = await upload(db, "pole", "poles.xlsx", xlsx([
        ["asset_code", "longitude", "latitude"], ["POLE-7000", 3.3541, 6.6003],
    ]))
    assert (again.valid_rows, again.duplicate_rows) == (0, 1)


async def test_cable_geojson_upload_resolves_endpoints(db):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "properties": {"cable_category": "feeder", "fiber_count": 48,
                        "source_asset_code": "OLT-IKJ-01", "dest_asset_code": "CAB-ALN-01", "cable_type": "adss"},
         "geometry": {"type": "LineString", "coordinates": [[3.3530, 6.6010], [3.3555, 6.6032]]}},
        {"type": "Feature",
         "properties": {"cable_category": "DROP", "source_asset_code": "NOPE-1"},
         "geometry": {"type": "LineString", "coordinates": [[3.3530, 6.6010], [3.3531, 6.6011]]}},
    ]}
    s, summary = await upload(db, "cable", "cables.geojson", json.dumps(fc).encode())
    assert (summary.valid_rows, summary.error_rows) == (1, 1)
    assert "no asset in the live network has code 'NOPE-1'" in summary.errors[0]["error"]

    assert (await commit_session(db, s.id, TENANT_A, ADMIN)).committed_rows == 1
    c = (await db.execute(text("""
        SELECT c.asset_code, c.route_method, c.creation_method, c.length_m, c.attributes,
               s.asset_code AS src, d.asset_code AS dst
        FROM net_cables c
        JOIN net_assets s ON s.id = c.source_asset_id
        JOIN net_assets d ON d.id = c.dest_asset_id
        WHERE c.source_table = 'infrastructure_upload_staging'
    """))).one()
    assert c.asset_code.startswith("FDR-") and c.route_method == "IMPORTED" and c.creation_method == "IMPORTED"
    assert (c.src, c.dst) == ("OLT-IKJ-01", "CAB-ALN-01")
    assert 300 < float(c.length_m) < 400 and c.attributes == {"cable_type": "ADSS"}


# ── Dual-write ───────────────────────────────────────────────

async def test_legacy_olt_upload_is_mirrored(db):
    s, summary = await upload(db, "olt", "olts.xlsx", xlsx([
        ["name", "location", "number_of_ODF", "longitude", "latitude"],
        ["OLT-DUAL-01", "Test POP", 2, 3.3600, 6.6050],
    ]))
    assert summary.valid_rows == 1
    assert (await commit_session(db, s.id, TENANT_A, ADMIN)).status == "committed"
    mirrored = (await db.execute(text("""
        SELECT asset_type, lifecycle_status, attributes->>'number_of_odf' AS odf
        FROM net_assets WHERE asset_code = 'OLT-DUAL-01' AND deleted_at IS NULL
    """))).one()
    assert tuple(mirrored) == ("OLT", "ACTIVE", "2")


async def test_bulk_deletion_retires_the_mirror(db):
    olt_id = (await db.execute(text("SELECT id FROM olts WHERE name = 'OLT-DUAL-01'"))).scalar_one()
    d = InfraDeletionSession(tenant_id=TENANT_A, asset_type="olt", status="validated",
                             original_filename="del.xlsx", submitted_by=ADMIN,
                             match_details=[{"status": "matched", "asset_id": str(olt_id)}])
    db.add(d)
    await db.flush()
    result = await execute_deletion(db, d.id, TENANT_A, ADMIN)
    assert result.status == "executed" and result.deleted_rows == 1
    gone = (await db.execute(text(
        "SELECT deleted_at IS NOT NULL FROM net_assets WHERE asset_code = 'OLT-DUAL-01'"))).scalar_one()
    assert gone


# ── Services ─────────────────────────────────────────────────

async def test_asset_service_generates_codes_and_checks_attributes(db):
    a = await service.create_asset(db, TENANT_A, CALLER, AssetCreate(
        asset_type="MANHOLE", geometry={"type": "Point", "coordinates": [3.3522, 6.6025]},
        attributes={"depth_m": "1.2", "cover_kind": "cast_iron"},
    ))
    assert a.asset_code.startswith("MH-") and a.attributes == {"depth_m": 1.2, "cover_kind": "CAST_IRON"}
    with pytest.raises(HTTPException) as exc:
        await service.update_asset(db, TENANT_A, CALLER, a.id, AssetUpdate(attributes={"depth_m": -3}))
    assert exc.value.status_code == 422 and "Depth" in exc.value.detail


async def test_cable_service_line_edit_and_lifecycle(db):
    c = await cable_service.create_cable(db, TENANT_A, CALLER, CableCreate(
        cable_category="DROP", route_method="IMPORTED", fiber_count=2, lifecycle_status="ACTIVE",
        geometry={"type": "LineString", "coordinates": [[3.3538, 6.5992], [3.3542, 6.5987]]},
    ))
    assert c.asset_code.startswith("DRP-") and c.route_method == "IMPORTED" and 60 < c.length_m < 80
    moved = await cable_service.update_cable(db, TENANT_A, CALLER, c.id, CableUpdate(
        geometry={"type": "LineString", "coordinates": [[3.3538, 6.5992], [3.3538, 6.6002]]},
    ))
    assert moved.route_method == "MANUAL_GEOMETRY" and 105 < moved.length_m < 115
    with pytest.raises(HTTPException) as exc:
        await cable_service.update_cable(db, TENANT_A, CALLER, c.id, CableUpdate(lifecycle_status="DRAFT"))
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        await cable_service.get_cable(db, TENANT_B, c.id)          # other tenant
    assert exc.value.status_code == 404
