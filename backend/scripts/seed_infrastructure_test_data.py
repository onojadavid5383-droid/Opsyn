#!/usr/bin/env python3
# ============================================================
# OPSYN SEED SCRIPT — scripts/seed_infrastructure_test_data.py
# Phase 1 seed data for Infrastructure Management module:
#   - 2 cabinets
#   - 1 OLT
#   - 2 First-Level splitters + 1 Second-Level splitter (linked to cabinet)
#
# Used for duplicate detection tests in Phase 2 validation engine.
#
# Usage: python -m scripts.seed_infrastructure_test_data
# Prerequisite: alembic upgrade head (migrations 0067–0074)
# ============================================================

import asyncio
import uuid

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import text
from app.core.database import AsyncSessionLocal

# Dev tenant UUID — must match migration 0027
DEV_TENANT_ID = uuid.UUID('00000000-0000-0000-0000-000000000001')

# Stable UUIDs (idempotent re-runs)
CABINET_1_ID   = uuid.UUID('cc000000-0000-0000-0000-000000000001')
CABINET_2_ID   = uuid.UUID('cc000000-0000-0000-0000-000000000002')
OLT_1_ID       = uuid.UUID('aa000000-0000-0000-0000-000000000001')
SPLIT_FL_1_ID  = uuid.UUID('bb000000-0000-0000-0000-000000000001')
SPLIT_FL_2_ID  = uuid.UUID('bb000000-0000-0000-0000-000000000002')
SPLIT_SL_1_ID  = uuid.UUID('bb000000-0000-0000-0000-000000000003')


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        # Set tenant context (bypass RLS for seed)
        await db.execute(
            text(f"SET LOCAL app.tenant_id = '{DEV_TENANT_ID}'")
        )

        # ── Cabinets ─────────────────────────────────────────
        await db.execute(text("""
            INSERT INTO cabinets
                (id, tenant_id, cabinet_id, capacity, number_tray,
                 longitude, latitude,
                 location, is_deleted, created_at, updated_at)
            VALUES
                (:id1, :tid, 'CAB-SEED-001', 48, 4,
                 3.3792, 6.5244,
                 ST_SetSRID(ST_MakePoint(3.3792, 6.5244), 4326),
                 FALSE, now(), now()),
                (:id2, :tid, 'CAB-SEED-002', 24, 2,
                 3.3800, 6.5250,
                 ST_SetSRID(ST_MakePoint(3.3800, 6.5250), 4326),
                 FALSE, now(), now())
            ON CONFLICT DO NOTHING
        """), {"id1": CABINET_1_ID, "id2": CABINET_2_ID, "tid": DEV_TENANT_ID})

        # ── OLT ──────────────────────────────────────────────
        await db.execute(text("""
            INSERT INTO olts
                (id, tenant_id, name, location_description, number_of_odf,
                 longitude, latitude,
                 location, is_deleted, created_at, updated_at)
            VALUES
                (:id, :tid,
                 'OLT-SURULERE-SEED-01',
                 '22 Bode Thomas Street, Surulere, Lagos',
                 16,
                 3.3600, 6.4900,
                 ST_SetSRID(ST_MakePoint(3.3600, 6.4900), 4326),
                 FALSE, now(), now())
            ON CONFLICT DO NOTHING
        """), {"id": OLT_1_ID, "tid": DEV_TENANT_ID})

        # ── Splitter Boxes ────────────────────────────────────
        await db.execute(text("""
            INSERT INTO splitter_boxes
                (id, tenant_id, box_id, input_ports, output_ports,
                 splitter_level, splitter_type, number_customer,
                 longitude, latitude, location,
                 cabinet_id, is_deleted, created_at, updated_at)
            VALUES
                -- First-Level #1 linked to Cabinet 1
                (:fl1, :tid, 'SPL-SEED-FL-001', 1, 8,
                 'First-Level', 'PCC', 6,
                 3.3792, 6.5244,
                 ST_SetSRID(ST_MakePoint(3.3792, 6.5244), 4326),
                 :cab1, FALSE, now(), now()),
                -- First-Level #2 linked to Cabinet 2
                (:fl2, :tid, 'SPL-SEED-FL-002', 1, 16,
                 'First-Level', 'Legacy', 10,
                 3.3800, 6.5250,
                 ST_SetSRID(ST_MakePoint(3.3800, 6.5250), 4326),
                 :cab2, FALSE, now(), now()),
                -- Second-Level linked to First-Level #1
                (:sl1, :tid, 'SPL-SEED-SL-001', 1, 8,
                 'Second-Level', 'PCC', 4,
                 3.3793, 6.5245,
                 ST_SetSRID(ST_MakePoint(3.3793, 6.5245), 4326),
                 :cab1, FALSE, now(), now())
            ON CONFLICT DO NOTHING
        """), {
            "fl1": SPLIT_FL_1_ID, "fl2": SPLIT_FL_2_ID,
            "sl1": SPLIT_SL_1_ID,
            "tid": DEV_TENANT_ID,
            "cab1": CABINET_1_ID, "cab2": CABINET_2_ID,
        })

        # Link Second-Level splitter to its First-Level parent
        await db.execute(text("""
            UPDATE splitter_boxes
            SET parent_splitter_id = :fl1
            WHERE id = :sl1 AND tenant_id = :tid
        """), {"fl1": SPLIT_FL_1_ID, "sl1": SPLIT_SL_1_ID, "tid": DEV_TENANT_ID})

        await db.commit()

        print("✔ Infrastructure seed data inserted:")
        print(f"  Cabinets:  CAB-SEED-001, CAB-SEED-002")
        print(f"  OLT:       OLT-SURULERE-SEED-01")
        print(f"  Splitters: SPL-SEED-FL-001 (First-Level), SPL-SEED-FL-002 (First-Level),")
        print(f"             SPL-SEED-SL-001 (Second-Level → parent: SPL-SEED-FL-001)")
        print()
        print("These records exist for Phase 2 duplicate detection tests.")
        print("Uploading an Excel file containing these box_id/cabinet_id values")
        print("should flag them as DUPLICATE (not ERROR) in the validation result.")


if __name__ == "__main__":
    asyncio.run(seed())
