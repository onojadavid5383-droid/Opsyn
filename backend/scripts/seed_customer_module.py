#!/usr/bin/env python3
# ============================================================
# OPSYN SEED SCRIPT — scripts/seed_customer_module.py
# Phase 1 seed data for Customer Module & Project Pipeline:
#   - One customer form schema (context='customer', is_active=True)
#   - Five field definitions: first_name, last_name, email, phone, service_plan
#   - Field visibility rules for stage 1 (creation)
#   - One mock customer (status='pending', source_app='manual')
#   - One payment_request (status='pending') linked to the mock customer
#
# Usage: python -m scripts.seed_customer_module
# Prerequisite: alembic upgrade head (migrations 0053–0064)
# ============================================================

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import select, text
from app.core.database import AsyncSessionLocal

# Dev tenant UUID — must match migration 0027
DEV_TENANT_ID = uuid.UUID('00000000-0000-0000-0000-000000000001')

# Stable UUIDs for seed data (idempotent re-runs)
SCHEMA_ID        = uuid.UUID('11000000-0000-0000-0000-000000000001')
CUSTOMER_ID      = uuid.UUID('11000000-0000-0000-0000-000000000002')
PAYMENT_REQ_ID   = uuid.UUID('11000000-0000-0000-0000-000000000003')

FIELD_IDS = {
    'first_name':   uuid.UUID('11000000-0000-0000-0001-000000000001'),
    'last_name':    uuid.UUID('11000000-0000-0000-0001-000000000002'),
    'email':        uuid.UUID('11000000-0000-0000-0001-000000000003'),
    'phone':        uuid.UUID('11000000-0000-0000-0001-000000000004'),
    'service_plan': uuid.UUID('11000000-0000-0000-0001-000000000005'),
}

VIS_RULE_IDS = {k: uuid.UUID(f'11000000-0000-0000-0002-{i+1:012d}')
                for i, k in enumerate(FIELD_IDS)}


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        # Set tenant context so RLS allows writes
        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {'tid': str(DEV_TENANT_ID)},
        )

        # ── 1. Form schema ─────────────────────────────────────
        existing_schema = (await db.execute(
            text("SELECT id FROM legacy_form_schemas WHERE id = :id"),
            {'id': str(SCHEMA_ID)},
        )).fetchone()

        if not existing_schema:
            await db.execute(text("""
                INSERT INTO legacy_form_schemas
                    (id, tenant_id, context, version, is_published, is_active,
                     title, description, created_at, updated_at)
                VALUES
                    (:id, :tid, 'customer', 1, true, true,
                     'Customer Onboarding Form',
                     'Default customer creation form for all pipeline stages',
                     now(), now())
            """), {
                'id':  str(SCHEMA_ID),
                'tid': str(DEV_TENANT_ID),
            })
            print("  ✓ form_schema created")
        else:
            print("  ✓ form_schema already exists — skipping")

        # ── 2. Field definitions ───────────────────────────────
        field_specs = [
            {
                'id': str(FIELD_IDS['first_name']),
                'key': 'first_name', 'label': 'First Name',
                'field_type': 'text', 'is_required': True,
                'validation_rules': '{"min_length": 2, "max_length": 100}',
                'visible_from_stage_order': 1, 'field_order': 0,
                'roles_can_edit': '{admin,manager,staff}',
            },
            {
                'id': str(FIELD_IDS['last_name']),
                'key': 'last_name', 'label': 'Last Name',
                'field_type': 'text', 'is_required': True,
                'validation_rules': '{"min_length": 2, "max_length": 100}',
                'visible_from_stage_order': 1, 'field_order': 1,
                'roles_can_edit': '{admin,manager,staff}',
            },
            {
                'id': str(FIELD_IDS['email']),
                'key': 'email', 'label': 'Email Address',
                'field_type': 'email', 'is_required': False,
                'validation_rules': '{"max_length": 255}',
                'visible_from_stage_order': 1, 'field_order': 2,
                'roles_can_edit': '{admin,manager,staff}',
            },
            {
                'id': str(FIELD_IDS['phone']),
                'key': 'phone', 'label': 'Phone Number',
                'field_type': 'phone', 'is_required': True,
                'validation_rules': '{"regex": "^\\\\+?[0-9]{7,15}$"}',
                'visible_from_stage_order': 1, 'field_order': 3,
                'roles_can_edit': '{admin,manager,staff}',
            },
            {
                'id': str(FIELD_IDS['service_plan']),
                'key': 'service_plan', 'label': 'Service Plan',
                'field_type': 'select', 'is_required': True,
                'validation_rules': (
                    '{"options_list": ["basic_10mbps", "standard_25mbps",'
                    ' "premium_50mbps", "business_100mbps"]}'
                ),
                'visible_from_stage_order': 1, 'field_order': 4,
                'roles_can_edit': '{admin,manager}',
            },
        ]

        for spec in field_specs:
            existing = (await db.execute(
                text("SELECT id FROM legacy_field_definitions WHERE id = :id"),
                {'id': spec['id']},
            )).fetchone()
            if not existing:
                await db.execute(text("""
                    INSERT INTO legacy_field_definitions
                        (id, tenant_id, form_schema_id, key, label, field_type,
                         validation_rules, is_required, visible_from_stage_order,
                         roles_can_edit, field_order, is_deleted, created_at, updated_at)
                    VALUES
                        (:id, :tid, :schema_id, :key, :label, :field_type,
                         CAST(:validation_rules AS JSONB), :is_required, :visible_from_stage_order,
                         CAST(:roles_can_edit AS TEXT[]), :field_order, false, now(), now())
                """), {
                    'id': spec['id'], 'tid': str(DEV_TENANT_ID),
                    'schema_id': str(SCHEMA_ID),
                    'key': spec['key'], 'label': spec['label'],
                    'field_type': spec['field_type'],
                    'validation_rules': spec['validation_rules'],
                    'is_required': spec['is_required'],
                    'visible_from_stage_order': spec['visible_from_stage_order'],
                    'roles_can_edit': spec['roles_can_edit'],
                    'field_order': spec['field_order'],
                })
                print(f"  ✓ field_definition '{spec['key']}' created")
            else:
                print(f"  ✓ field_definition '{spec['key']}' exists — skipping")

        # ── 3. Field visibility rules (stage 1, no dept filter) ─
        # dept_id = NULL means visible to all departments at stage 1
        # We'll insert with a sentinel approach; use a known Finance dept if available
        finance_dept = (await db.execute(
            text("SELECT id FROM departments WHERE tenant_id = :tid AND name ILIKE '%finance%' LIMIT 1"),
            {'tid': str(DEV_TENANT_ID)},
        )).fetchone()

        if finance_dept:
            dept_id = str(finance_dept[0])
            for key, field_id in FIELD_IDS.items():
                rule_id = str(VIS_RULE_IDS[key])
                existing = (await db.execute(
                    text("SELECT id FROM field_visibility_rules WHERE id = :id"),
                    {'id': rule_id},
                )).fetchone()
                if not existing:
                    is_required = key in ('first_name', 'last_name', 'phone', 'service_plan')
                    await db.execute(text("""
                        INSERT INTO field_visibility_rules
                            (id, tenant_id, field_definition_id, stage_order,
                             department_id, is_required_to_advance, created_at)
                        VALUES
                            (:id, :tid, :field_id, 1, :dept_id, :required, now())
                    """), {
                        'id': rule_id, 'tid': str(DEV_TENANT_ID),
                        'field_id': str(field_id), 'dept_id': dept_id,
                        'required': is_required,
                    })
                    print(f"  ✓ visibility rule for '{key}' at stage 1")
        else:
            print("  ℹ  No finance department found — skipping visibility rules (run seed.py first)")

        # ── 4. Mock customer ───────────────────────────────────
        existing_cust = (await db.execute(
            text("SELECT id FROM customers WHERE id = :id"),
            {'id': str(CUSTOMER_ID)},
        )).fetchone()

        if not existing_cust:
            await db.execute(text("""
                INSERT INTO customers
                    (id, tenant_id, first_name, last_name, email, phone,
                     status, source_app, external_ref_id,
                     is_deleted, created_at, updated_at)
                VALUES
                    (:id, :tid, 'Test', 'Customer', 'test.customer@example.com',
                     '+2348012345678', 'pending', 'manual', 'SEED-MOCK-0001',
                     false, now(), now())
            """), {
                'id':  str(CUSTOMER_ID),
                'tid': str(DEV_TENANT_ID),
            })
            print("  ✓ mock customer created")
        else:
            print("  ✓ mock customer exists — skipping")

        # ── 5. Payment request (pending) ───────────────────────
        existing_pr = (await db.execute(
            text("SELECT id FROM payment_requests WHERE id = :id"),
            {'id': str(PAYMENT_REQ_ID)},
        )).fetchone()

        if not existing_pr:
            expires = datetime.now(timezone.utc) + timedelta(days=7)
            await db.execute(text("""
                INSERT INTO payment_requests
                    (id, tenant_id, customer_id, amount, currency,
                     payment_link, status, expires_at, created_at, updated_at)
                VALUES
                    (:id, :tid, :cust_id, 15000.00, 'NGN',
                     'https://pay.opsyn.internal/pending/SEED-MOCK-0001',
                     'pending', :expires, now(), now())
            """), {
                'id':     str(PAYMENT_REQ_ID),
                'tid':    str(DEV_TENANT_ID),
                'cust_id': str(CUSTOMER_ID),
                'expires': expires,
            })
            print("  ✓ payment_request (pending) created")
        else:
            print("  ✓ payment_request exists — skipping")

        await db.commit()
        print("\n✅ Customer module seed complete.")

        # ── Tenant isolation check ──────────────────────────────
        wrong_tid = uuid.UUID('00000000-0000-0000-0000-000000000999')
        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {'tid': str(wrong_tid)},
        )
        row = (await db.execute(
            text("SELECT id FROM customers WHERE id = :id"),
            {'id': str(CUSTOMER_ID)},
        )).fetchone()
        if row is None:
            print("✅ Tenant isolation confirmed: wrong tenant sees zero rows.")
        else:
            print("❌ WARNING: Tenant isolation FAILED — RLS may not be active!")


if __name__ == '__main__':
    asyncio.run(seed())
