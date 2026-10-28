# ============================================================
# OPSYN TENANT SETUP SERVICE — app/modules/tenants/setup_service.py
# Provisions every new FTTx subscriber with baseline template data:
#   8 default roles, 5 dept placeholders, 12 permission keys,
#   1 region placeholder, default feature grants.
# ============================================================

from __future__ import annotations
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


# 12 feature permission keys seeded globally (once, not per tenant)
FEATURE_PERMISSION_KEYS = [
    ("staff.create",       "Create Staff",              "staff",          "Create new staff members"),
    ("onboarding.manage",  "Manage Onboarding",         "onboarding",     "Review and approve onboarding requests"),
    ("outage.log",         "Log Outages",               "outage",         "Report new outage incidents"),
    ("outage.manage",      "Manage Outages",            "outage",         "Update and resolve outage incidents"),
    ("infrastructure.view","View Infrastructure",       "infrastructure", "View infrastructure map and status"),
    ("infrastructure.edit","Edit Infrastructure",       "infrastructure", "Add/edit infrastructure sites and routes"),
    ("leads.manage",       "Manage Leads",              "projects",       "Create and manage sales leads"),
    ("tasks.manage",       "Manage Tasks",              "tasks",          "Create, assign, and update tasks"),
    ("reports.view",       "View Reports",              "reports",        "Access operational reports"),
    ("reports.financial",  "View Financial Reports",    "reports",        "Access financial and cost reports"),
    ("pipeline.advance",   "Advance Pipeline",          "projects",       "Move projects through pipeline stages"),
    ("settings.admin",     "Administration Settings",   "settings",       "Configure system settings"),
]

# Default FTTx department placeholders
DEFAULT_DEPARTMENTS = [
    "Network Operations",
    "Field Operations",
    "MEC/Maintenance",
    "Management",
    "Customer Experience",
]

# Default role definitions: (name, level)
DEFAULT_ROLES = [
    ("Admin",            5),
    ("Manager",          4),
    ("Team Lead",        3),
    ("NOC Operator",     2),
    ("MEC Reviewer",     2),
    ("Field Technician", 2),
    ("Executive Viewer", 2),
    ("Staff",            1),
]

# Default feature grants per department: (dept_name, feature_key, min_role_level)
DEFAULT_DEPT_GRANTS = [
    ("Network Operations",  "outage.log",          2),
    ("Network Operations",  "outage.manage",       3),
    ("Network Operations",  "tasks.manage",        2),
    ("Network Operations",  "infrastructure.view", 2),
    ("Network Operations",  "pipeline.advance",    3),
    ("Field Operations",    "tasks.manage",        2),
    ("Field Operations",    "outage.log",          2),
    ("Field Operations",    "infrastructure.view", 2),
    ("Field Operations",    "pipeline.advance",    3),
    ("MEC/Maintenance",     "tasks.manage",        2),
    ("MEC/Maintenance",     "infrastructure.view", 2),
    ("MEC/Maintenance",     "infrastructure.edit", 3),
    ("MEC/Maintenance",     "pipeline.advance",    3),
    ("Management",          "reports.view",        3),
    ("Management",          "reports.financial",   4),
    ("Management",          "staff.create",        4),
    ("Management",          "onboarding.manage",   4),
    ("Management",          "pipeline.advance",    3),
    ("Management",          "settings.admin",      5),
    ("Customer Experience", "leads.manage",        2),
    ("Customer Experience", "tasks.manage",        2),
    ("Customer Experience", "pipeline.advance",    3),
]


async def seed_global_feature_permissions(db: AsyncSession) -> None:
    """Seed feature_permissions table (global, not tenant-scoped). Idempotent."""
    for feature_key, feature_label, module, description in FEATURE_PERMISSION_KEYS:
        await db.execute(text("""
            INSERT INTO feature_permissions (feature_key, feature_label, module, description)
            VALUES (:key, :label, :module, :desc)
            ON CONFLICT (feature_key) DO NOTHING
        """), {"key": feature_key, "label": feature_label, "module": module, "desc": description})


async def apply_fttx_template(
    db:        AsyncSession,
    tenant_id: uuid.UUID,
    admin_user_id: uuid.UUID,
) -> dict:
    """
    Provision a new FTTx tenant with:
    - 8 default roles
    - 5 placeholder departments
    - 1 placeholder region
    - 12 feature permission keys (global seed)
    - Default department feature grants

    Returns: dict with created IDs for reference.
    """
    result: dict = {"roles": [], "departments": [], "region_id": None}

    # ── Create default roles ──────────────────────────────────
    role_ids: dict[str, uuid.UUID] = {}
    for role_name, role_level in DEFAULT_ROLES:
        role_id = uuid.uuid4()
        await db.execute(text("""
            INSERT INTO roles (id, tenant_id, name, level, is_system_role)
            VALUES (:id, :tenant_id, :name, :level, true)
            ON CONFLICT DO NOTHING
        """), {
            "id": role_id, "tenant_id": tenant_id,
            "name": role_name, "level": role_level,
        })
        role_ids[role_name] = role_id
        result["roles"].append({"name": role_name, "level": role_level, "id": str(role_id)})

    # ── Create default departments ────────────────────────────
    dept_ids: dict[str, uuid.UUID] = {}
    for dept_name in DEFAULT_DEPARTMENTS:
        new_id = uuid.uuid4()
        await db.execute(text("""
            INSERT INTO departments (id, tenant_id, name)
            VALUES (:id, :tenant_id, :name)
            ON CONFLICT DO NOTHING
        """), {"id": new_id, "tenant_id": tenant_id, "name": dept_name})
        # Ensure we use an actual row id (either newly created or existing).
        # Repeated seed runs can leave duplicate department rows from older data;
        # choosing the first valid row keeps the bootstrap idempotent without
        # raising MultipleResultsFound during setup.
        row = (await db.execute(text("""
            SELECT id
            FROM departments
            WHERE name = :name AND tenant_id = :tenant_id
            ORDER BY id
            LIMIT 1
        """), {"name": dept_name, "tenant_id": tenant_id})).scalar()
        if row is None:
            raise RuntimeError(f"Department '{dept_name}' was not created for tenant {tenant_id}")
        dept_id = row
        dept_ids[dept_name] = dept_id
        result["departments"].append({"name": dept_name, "id": str(dept_id)})

    # ── Create placeholder region ─────────────────────────────
    new_region_id = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO regions (id, tenant_id, name, code)
        VALUES (:id, :tenant_id, :name, :code)
        ON CONFLICT DO NOTHING
    """), {
        "id": new_region_id, "tenant_id": tenant_id,
        "name": "Default Region", "code": "DEF",
    })
    region_row = (await db.execute(text("""
        SELECT id
        FROM regions
        WHERE code = :code AND tenant_id = :tenant_id
        ORDER BY id
        LIMIT 1
    """), {"code": "DEF", "tenant_id": tenant_id})).scalar()
    if region_row is None:
        raise RuntimeError(f"Default region was not created for tenant {tenant_id}")
    result["region_id"] = str(region_row)

    # ── Seed global feature permissions ──────────────────────
    await seed_global_feature_permissions(db)

    # ── Create default department feature grants ──────────────
    for dept_name, feature_key, min_role_level in DEFAULT_DEPT_GRANTS:
        dept_id = dept_ids.get(dept_name)
        if not dept_id:
            continue
        await db.execute(text("""
            INSERT INTO department_feature_grants
                (id, tenant_id, department_id, feature_key, min_role_level, granted_by)
            VALUES (
                gen_random_uuid(), :tenant_id, :dept_id, :feature_key, :min_role_level,
                CASE WHEN EXISTS (SELECT 1 FROM users WHERE id = :granted_by) THEN :granted_by ELSE NULL END
            )
            ON CONFLICT (tenant_id, department_id, feature_key) DO NOTHING
        """), {
            "tenant_id": tenant_id, "dept_id": dept_id,
            "feature_key": feature_key, "min_role_level": min_role_level,
            "granted_by": admin_user_id,
        })

    # ── Seed 4 blank legacy form schemas ─────────────────────────
    # Targets legacy_form_schemas (renamed from form_schemas in migration 0076).
    form_contexts = [
        ("lead",        "Lead Capture Form"),
        ("task",        "Task Submission Form"),
        ("project",     "Project Initiation Form"),
        ("onboarding",  "Staff Onboarding Form"),
    ]
    for context, title in form_contexts:
        await db.execute(text("""
            INSERT INTO legacy_form_schemas (id, tenant_id, context, version, is_published, title, created_by)
            VALUES (
                gen_random_uuid(), :tenant_id, :context, 1, false, :title,
                CASE WHEN EXISTS (SELECT 1 FROM users WHERE id = :created_by) THEN :created_by ELSE NULL END
            )
            ON CONFLICT DO NOTHING
        """), {
            "tenant_id":  tenant_id,
            "context":    context,
            "title":      title,
            "created_by": admin_user_id,
        })

    return result
