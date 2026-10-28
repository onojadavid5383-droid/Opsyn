#!/usr/bin/env python3
# ============================================================
# OPSYN SEED SCRIPT — scripts/seed.py
# Full bootstrap for the dev tenant:
#   - Tenant + FTTx template (roles, depts, feature permissions,
#     dept grants, form schemas, placeholder region)
#   - Dev regions (Lagos, Abuja, PHC, Kano, Enugu, Ibadan)
#   - Admin user (level 5) + Manager user (level 4)
#   - Demo infrastructure sites, OLT nodes, a fibre route
#   - Demo SmartOLT config (uses env API key if set)
# Usage: python -m scripts.seed
# ============================================================

import asyncio
import uuid
from datetime import date
from sqlalchemy import select, text

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.modules.organisation.models import Department, Team, Region
from app.modules.all_modules import Role
from app.modules.staff.models import User, StaffProfile
from app.modules.tenants.models import Tenant
from app.modules.tenants.setup_service import apply_fttx_template, seed_global_feature_permissions

# Dev tenant — must match the UUID in migration 0027
DEV_TENANT_ID = uuid.UUID('00000000-0000-0000-0000-000000000001')


# ── Users to seed ─────────────────────────────────────────────
ADMIN_USER = {
    "username":  "david.onoja",
    "email":     "admin@opsyn.ng",
    "password":  "opsyn_admin_2026",
    "first_name": "David",
    "last_name":  "Onoja",
    "staff_code": "ADM-0001",
    "job_title":  "System Administrator",
    "dept":       "Management",
    "role_name":  "Admin",
}

MANAGER_USER = {
    "username":  "manager.test",
    "email":     "manager@opsyn.ng",
    "password":  "opsyn_manager_2026",
    "first_name": "Test",
    "last_name":  "Manager",
    "staff_code": "MGR-0001",
    "job_title":  "Network Operations Manager",
    "dept":       "Network Operations",
    "role_name":  "Manager",
}

# ── Extra regions beyond the template placeholder ─────────────
EXTRA_REGIONS = [
    {"name": "Lagos",         "code": "LOS"},
    {"name": "Abuja",         "code": "ABJ"},
    {"name": "Port Harcourt", "code": "PHC"},
    {"name": "Kano",          "code": "KAN"},
    {"name": "Enugu",         "code": "ENU"},
    {"name": "Ibadan",        "code": "IBA"},
]

# ── Demo infrastructure ───────────────────────────────────────
DEMO_SITES = [
    {"name": "Victoria Island POP",  "site_type": "POP",  "address": "Ozumba Mbadiwe Ave, VI, Lagos",       "lat":  6.4280, "lng": 3.4219},
    {"name": "Lekki Phase 1 POP",    "site_type": "POP",  "address": "Admiralty Way, Lekki, Lagos",         "lat":  6.4331, "lng": 3.4723},
    {"name": "Ikeja Hub",            "site_type": "HUB",  "address": "Obafemi Awolowo Way, Ikeja, Lagos",   "lat":  6.5958, "lng": 3.3458},
    {"name": "Wuse Zone 5 POP",      "site_type": "POP",  "address": "Wuse Zone 5, Abuja FCT",              "lat":  9.0820, "lng": 7.4916},
    {"name": "Maitama Data Centre",  "site_type": "DC",   "address": "Maitama, Abuja FCT",                  "lat":  9.0821, "lng": 7.5074},
]

DEMO_NODES = [
    {"name": "VI-OLT-01",    "node_type": "OLT",    "site_name": "Victoria Island POP",  "ip": "10.10.1.1"},
    {"name": "VI-OLT-02",    "node_type": "OLT",    "site_name": "Victoria Island POP",  "ip": "10.10.1.2"},
    {"name": "LEK-OLT-01",   "node_type": "OLT",    "site_name": "Lekki Phase 1 POP",    "ip": "10.10.2.1"},
    {"name": "IKJ-AGG-01",   "node_type": "AGG",    "site_name": "Ikeja Hub",            "ip": "10.20.1.1"},
    {"name": "WSZ5-OLT-01",  "node_type": "OLT",    "site_name": "Wuse Zone 5 POP",      "ip": "10.30.1.1"},
    {"name": "MTM-CORE-01",  "node_type": "CORE",   "site_name": "Maitama Data Centre",  "ip": "10.30.0.1"},
]

DEMO_ROUTES = [
    {"name": "VI–Lekki Fibre",     "from_node": "VI-OLT-01",   "to_node": "LEK-OLT-01",  "cable_type": "GPON", "length_km": 12.5},
    {"name": "VI–Ikeja Backbone",  "from_node": "VI-OLT-01",   "to_node": "IKJ-AGG-01",  "cable_type": "DWDM", "length_km": 28.0},
    {"name": "Wuse–Maitama Ring",  "from_node": "WSZ5-OLT-01", "to_node": "MTM-CORE-01", "cable_type": "GPON", "length_km":  7.2},
]


async def _get_or_create_role(db, name: str, level: int, tenant_id: uuid.UUID) -> "Role":
    existing = (await db.execute(
        select(Role).where(Role.tenant_id == tenant_id, Role.name == name)
    )).scalars().first()
    if existing:
        return existing
    role = Role(name=name, level=level, tenant_id=tenant_id, is_system_role=True)
    db.add(role)
    await db.flush()
    return role


async def _get_or_create_dept(db, name: str, tenant_id: uuid.UUID) -> "Department":
    existing = (await db.execute(
        select(Department).where(Department.name == name, Department.tenant_id == tenant_id)
    )).scalars().first()
    if existing:
        return existing
    dept = Department(name=name, tenant_id=tenant_id)
    db.add(dept)
    await db.flush()
    return dept


async def _create_user(
    db, user_def: dict, tenant_id: uuid.UUID,
    role: "Role", dept: "Department", creator_id: uuid.UUID
) -> "User":
    existing = (await db.execute(
        select(User).where(User.email == user_def["email"])
    )).scalars().first()

    if existing:
        # Update password hash so dev credentials always work after re-seed
        existing.password_hash = hash_password(user_def["password"])
        existing.is_active = True
        if existing.staff_profile:
            existing.staff_profile.first_name = user_def["first_name"]
            existing.staff_profile.last_name  = user_def["last_name"]
            existing.staff_profile.status     = "active"
        print(f"  · User updated: {user_def['email']}")
        return existing

    user = User(
        tenant_id=tenant_id,
        username=user_def["username"],
        email=user_def["email"],
        password_hash=hash_password(user_def["password"]),
        role_id=role.id,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    profile = StaffProfile(
        user_id=user.id,
        tenant_id=tenant_id,
        staff_code=user_def["staff_code"],
        first_name=user_def["first_name"],
        last_name=user_def["last_name"],
        job_title=user_def.get("job_title"),
        department_id=dept.id,
        status="active",
        employment_type="permanent",
        joined_at=date.today(),
        created_by=creator_id,
    )
    db.add(profile)
    await db.flush()
    print(f"  ✓ User created: {user_def['email']} / {user_def['password']}")
    return user


async def seed():
    async with AsyncSessionLocal() as db:
        print("\n🌱 Opsyn full database seed — Powered by SlimTech")
        print("─" * 55)

        # ── Ensure dev tenant exists ───────────────────────────
        tenant = (await db.execute(
            select(Tenant).where(Tenant.id == DEV_TENANT_ID)
        )).scalars().first()

        if not tenant:
            tenant = Tenant(
                id=DEV_TENANT_ID,
                name="Opsyn Development",
                slug="opsyn-dev",
                plan="enterprise",
                is_active=True,
                settings={},
            )
            db.add(tenant)
            await db.flush()
            print("  ✓ Dev tenant created")
        else:
            print("  · Dev tenant exists")

        # ── Apply FTTx template (idempotent) ───────────────────
        # Uses a placeholder creator id; real admin user is created later
        placeholder_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
        print("  ↳ Applying FTTx template (roles, depts, feature permissions)…")
        await apply_fttx_template(db, DEV_TENANT_ID, placeholder_id)
        print("  ✓ FTTx template applied")

        # ── Extra regions ──────────────────────────────────────
        for r in EXTRA_REGIONS:
            existing = (await db.execute(
                select(Region).where(Region.code == r["code"], Region.tenant_id == DEV_TENANT_ID)
            )).scalars().first()
            if not existing:
                db.add(Region(name=r["name"], code=r["code"], tenant_id=DEV_TENANT_ID))
                print(f"  ✓ Region: {r['name']}")

        await db.flush()

        # ── Teams ──────────────────────────────────────────────
        noc_dept = (await db.execute(
            select(Department).where(Department.name == "Network Operations", Department.tenant_id == DEV_TENANT_ID)
        )).scalars().first()

        if noc_dept:
            for team_name in ["Team Alpha", "Team Beta", "Team Gamma"]:
                exists = (await db.execute(
                    select(Team).where(Team.name == team_name, Team.department_id == noc_dept.id)
                )).scalars().first()
                if not exists:
                    db.add(Team(name=team_name, department_id=noc_dept.id, tenant_id=DEV_TENANT_ID))
                    print(f"  ✓ Team: {team_name}")

        await db.flush()

        # ── Users ──────────────────────────────────────────────
        admin_role = (await db.execute(
            select(Role).where(Role.tenant_id == DEV_TENANT_ID, Role.name == "Admin")
        )).scalars().first()
        mgr_role = (await db.execute(
            select(Role).where(Role.tenant_id == DEV_TENANT_ID, Role.name == "Manager")
        )).scalars().first()
        mgmt_dept = (await db.execute(
            select(Department).where(Department.tenant_id == DEV_TENANT_ID, Department.name == "Management")
        )).scalars().first()

        if not admin_role:
            admin_role = await _get_or_create_role(db, "Admin", 5, DEV_TENANT_ID)
        if not mgr_role:
            mgr_role = await _get_or_create_role(db, "Manager", 4, DEV_TENANT_ID)
        if not mgmt_dept:
            mgmt_dept = await _get_or_create_dept(db, "Management", DEV_TENANT_ID)
        noc_dept = noc_dept or await _get_or_create_dept(db, "Network Operations", DEV_TENANT_ID)

        # Admin user — prefer to reuse existing user if present (by id/email/username)
        FIXED_ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
        existing_admin = (await db.execute(
            select(User).where(
                User.tenant_id == DEV_TENANT_ID,
                (User.id == FIXED_ADMIN_ID) | (User.email == ADMIN_USER["email"]) | (User.username == ADMIN_USER["username"])
            )
        )).scalars().first()

        if existing_admin:
            # Use whichever id the existing user has (avoid inserting duplicate username)
            admin_id = existing_admin.id
            existing_admin.password_hash = hash_password(ADMIN_USER["password"])
            existing_admin.is_active = True
            # Ensure staff profile exists/updated
            if existing_admin.staff_profile:
                existing_admin.staff_profile.first_name = ADMIN_USER["first_name"]
                existing_admin.staff_profile.last_name = ADMIN_USER["last_name"]
                existing_admin.staff_profile.status = "active"
            else:
                db.add(StaffProfile(
                    user_id=admin_id, tenant_id=DEV_TENANT_ID,
                    staff_code=ADMIN_USER["staff_code"],
                    first_name=ADMIN_USER["first_name"], last_name=ADMIN_USER["last_name"],
                    job_title=ADMIN_USER["job_title"], department_id=mgmt_dept.id,
                    status="active", employment_type="permanent",
                    joined_at=date.today(), created_by=admin_id,
                ))
            await db.flush()
            print(f"  · Admin exists/updated: {ADMIN_USER['email']}")
        else:
            # Insert a new admin with the fixed UUID so FK references in seed can use it
            admin_id = FIXED_ADMIN_ID
            admin_user = User(
                id=admin_id,
                tenant_id=DEV_TENANT_ID,
                username=ADMIN_USER["username"],
                email=ADMIN_USER["email"],
                password_hash=hash_password(ADMIN_USER["password"]),
                role_id=admin_role.id,
                is_active=True,
            )
            db.add(admin_user)
            await db.flush()
            db.add(StaffProfile(
                user_id=admin_id, tenant_id=DEV_TENANT_ID,
                staff_code=ADMIN_USER["staff_code"],
                first_name=ADMIN_USER["first_name"], last_name=ADMIN_USER["last_name"],
                job_title=ADMIN_USER["job_title"], department_id=mgmt_dept.id,
                status="active", employment_type="permanent",
                joined_at=date.today(), created_by=admin_id,
            ))
            await db.flush()
            print(f"  ✓ Admin created: {ADMIN_USER['email']} / {ADMIN_USER['password']}")

        await _create_user(db, MANAGER_USER, DEV_TENANT_ID, mgr_role, noc_dept, admin_id)

        await db.flush()

        # ── Demo infrastructure ────────────────────────────────
        print("\n  📡 Seeding demo infrastructure…")
        from app.modules.infrastructure.models import (
            InfrastructureSite, InfrastructureNode, InfrastructureRoute
        )

        # Lagos region
        lagos = (await db.execute(
            select(Region).where(Region.code == "LOS", Region.tenant_id == DEV_TENANT_ID)
        )).scalars().first()
        abuja = (await db.execute(
            select(Region).where(Region.code == "ABJ", Region.tenant_id == DEV_TENANT_ID)
        )).scalars().first()

        site_map: dict[str, uuid.UUID] = {}
        for s in DEMO_SITES:
            existing_site = (await db.execute(
                select(InfrastructureSite).where(
                    InfrastructureSite.name == s["name"],
                    InfrastructureSite.tenant_id == DEV_TENANT_ID,
                )
            )).scalars().first()
            if not existing_site:
                region = lagos if "Lagos" in s["address"] or "Lekki" in s["address"] or "Ikeja" in s["address"] else abuja
                site = InfrastructureSite(
                    tenant_id=DEV_TENANT_ID,
                    name=s["name"], site_type=s["site_type"],
                    address=s["address"], latitude=s.get("lat"), longitude=s.get("lng"),
                    region_id=region.id if region else None,
                    status="active", created_by=admin_id,
                )
                db.add(site)
                await db.flush()
                site_map[s["name"]] = site.id
                print(f"  ✓ Site: {s['name']}")
            else:
                site_map[s["name"]] = existing_site.id

        node_map: dict[str, uuid.UUID] = {}
        for n in DEMO_NODES:
            existing_node = (await db.execute(
                select(InfrastructureNode).where(
                    InfrastructureNode.name == n["name"],
                    InfrastructureNode.tenant_id == DEV_TENANT_ID,
                )
            )).scalars().first()
            if not existing_node:
                node = InfrastructureNode(
                    tenant_id=DEV_TENANT_ID,
                    name=n["name"], node_type=n["node_type"],
                    site_id=site_map.get(n["site_name"]),
                    ip_address=n.get("ip"),
                    status="active", created_by=admin_id,
                )
                db.add(node)
                await db.flush()
                node_map[n["name"]] = node.id
                print(f"  ✓ Node: {n['name']} ({n['node_type']})")
            else:
                node_map[n["name"]] = existing_node.id

        for r in DEMO_ROUTES:
            fn_id = node_map.get(r["from_node"])
            tn_id = node_map.get(r["to_node"])
            if not fn_id or not tn_id:
                print(f"  ! Skipping route {r['name']} — node not found")
                continue
            existing_route = (await db.execute(
                select(InfrastructureRoute).where(
                    InfrastructureRoute.from_node_id == fn_id,
                    InfrastructureRoute.to_node_id == tn_id,
                    InfrastructureRoute.tenant_id == DEV_TENANT_ID,
                )
            )).scalars().first()
            if not existing_route:
                route = InfrastructureRoute(
                    tenant_id=DEV_TENANT_ID,
                    from_node_id=fn_id,
                    to_node_id=tn_id,
                    cable_type=r["cable_type"],
                    length_km=r["length_km"],
                    status="active", created_by=admin_id,
                    notes=r["name"],
                )
                db.add(route)
                await db.flush()
                print(f"  ✓ Route: {r['name']}")

        # ── Feature permissions (global, idempotent) ───────────
        await seed_global_feature_permissions(db)
        print("  ✓ Feature permissions seeded")

        await db.commit()

        print("\n✅ Seed complete — Opsyn is ready.")
        print("\n   Credentials:")
        print(f"   Admin:   {ADMIN_USER['email']}   / {ADMIN_USER['password']}")
        print(f"   Manager: {MANAGER_USER['email']} / {MANAGER_USER['password']}")
        print(f"\n   Frontend: http://localhost:5173")
        print(f"   API docs: http://localhost:8000/api/docs")
        print()


if __name__ == "__main__":
    asyncio.run(seed())
