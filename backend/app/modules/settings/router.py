# ============================================================
# OPSYN SETTINGS ROUTER — app/modules/settings/router.py
# Admin settings API: departments, roles, features, regions,
# organisation profile, and pipeline templates.
# All endpoints require authentication. Most require Admin level.
# ============================================================

from __future__ import annotations
import uuid, json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, text, update, cast
from sqlalchemy.dialects.postgresql import JSONB as PgJSONB
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.context import tenant_id_ctx
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import check_permission
from app.modules.staff.models import User
from app.modules.organisation.models import Department, Region
from app.modules.projects.models import PipelineTemplate, PipelineTemplateStage
from app.modules.tenants.models import Tenant

router = APIRouter()


# ── Pydantic Schemas ─────────────────────────────────────────

class DeptCreate(BaseModel):
    name:         str
    parent_id:    Optional[uuid.UUID] = None
    head_user_id: Optional[uuid.UUID] = None


class DeptUpdate(BaseModel):
    name:         Optional[str]       = None
    parent_id:    Optional[uuid.UUID] = None
    head_user_id: Optional[uuid.UUID] = None


class DeptFeatureGrant(BaseModel):
    feature_key:   str
    min_role_level: int = 1


class RoleCreate(BaseModel):
    name:        str
    level:       int
    description: Optional[str] = None


class RegionCreate(BaseModel):
    name:      str
    code:      str
    parent_id: Optional[uuid.UUID] = None


class OrgSettingsUpdate(BaseModel):
    name:     Optional[str]  = None
    timezone: Optional[str]  = None
    logo_url: Optional[str]  = None


class OrgBrandUpdate(BaseModel):
    primary_color:   Optional[str] = None
    logo_url:        Optional[str] = None
    favicon_url:     Optional[str] = None
    company_tagline: Optional[str] = None


class PipelineCreate(BaseModel):
    name:        str
    description: Optional[str] = None


class PipelineStageUpsert(BaseModel):
    stage_order:            int
    stage_name:             str
    department_id:          uuid.UUID
    is_required:            bool = True
    is_parallel:            bool = False
    expected_duration_days: Optional[int] = None


class PipelineStagesUpdate(BaseModel):
    stages: list[PipelineStageUpsert]


# ── Organisation Profile ─────────────────────────────────────

@router.get("/organisation")
async def get_org_settings(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(get_current_user),
):
    """Return the calling tenant's settings."""
    tenant_id = tenant_id_ctx.get()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant context.")

    row = (await db.execute(
        text("SELECT id, name, slug, plan, max_users, is_active, settings FROM tenants WHERE id = :id"),
        {"id": str(tenant_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    return {
        "success": True,
        "data": {
            "id":        str(row[0]),
            "name":      row[1],
            "slug":      row[2],
            "plan":      row[3],
            "max_users": row[4],
            "is_active": row[5],
            "settings":  row[6] or {},
        },
    }


@router.patch("/organisation")
async def update_org_settings(
    payload: OrgSettingsUpdate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    """Update tenant name or settings. Admin only."""
    tenant_id = tenant_id_ctx.get()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant context.")

    import json

    values: dict = {}
    if payload.name:
        values["name"] = payload.name

    extra: dict = {}
    if payload.timezone:
        extra["timezone"] = payload.timezone
    if payload.logo_url:
        extra["logo_url"] = payload.logo_url
    if extra:
        values["settings"] = Tenant.settings.op("||")(cast(json.dumps(extra), PgJSONB))

    if values:
        await db.execute(
            update(Tenant).where(Tenant.id == tenant_id).values(**values)
        )
        await db.commit()
    return {"success": True, "message": "Organisation settings updated."}


# ── Departments ───────────────────────────────────────────────

@router.get("/departments")
async def list_departments(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(get_current_user),
):
    rows = (await db.execute(
        select(Department).order_by(Department.name)
    )).scalars().all()
    return {
        "success": True,
        "data": [
            {
                "id":           str(d.id),
                "name":         d.name,
                "parent_id":    str(d.parent_id)    if d.parent_id    else None,
                "head_user_id": str(d.head_user_id) if d.head_user_id else None,
            }
            for d in rows
        ],
    }


@router.post("/departments", status_code=201)
async def create_department(
    payload: DeptCreate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    tenant_id = tenant_id_ctx.get()
    dept = Department(
        tenant_id=tenant_id,
        name=payload.name,
        parent_id=payload.parent_id,
        head_user_id=payload.head_user_id,
    )
    db.add(dept)
    await db.flush()
    return {"success": True, "data": {"id": str(dept.id), "name": dept.name}}


@router.put("/departments/{dept_id}")
async def update_department(
    dept_id: uuid.UUID   = Path(...),
    payload: DeptUpdate  = ...,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    dept = (await db.execute(
        select(Department).where(Department.id == dept_id)
    )).scalar_one_or_none()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found.")
    if payload.name:
        dept.name = payload.name
    if payload.parent_id is not None:
        dept.parent_id = payload.parent_id
    if payload.head_user_id is not None:
        dept.head_user_id = payload.head_user_id
    await db.flush()
    return {"success": True, "data": {"id": str(dept.id), "name": dept.name}}


@router.delete("/departments/{dept_id}", status_code=204)
async def delete_department(
    dept_id: uuid.UUID   = Path(...),
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    dept = (await db.execute(
        select(Department).where(Department.id == dept_id)
    )).scalar_one_or_none()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found.")
    await db.delete(dept)


# ── Department Feature Access ─────────────────────────────────

@router.get("/departments/{dept_id}/features")
async def list_dept_features(
    dept_id: uuid.UUID   = Path(...),
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    tenant_id = tenant_id_ctx.get()
    rows = (await db.execute(
        text("""
            SELECT feature_key, min_role_level, granted_at
            FROM department_feature_grants
            WHERE tenant_id = :tenant_id AND department_id = :dept_id
            ORDER BY feature_key
        """),
        {"tenant_id": str(tenant_id), "dept_id": str(dept_id)},
    )).fetchall()
    return {
        "success": True,
        "data": [
            {
                "feature_key":   r[0],
                "min_role_level": r[1],
                "granted_at":    r[2].isoformat() if r[2] else None,
            }
            for r in rows
        ],
    }


@router.post("/departments/{dept_id}/features", status_code=201)
async def grant_dept_feature(
    dept_id: uuid.UUID       = Path(...),
    payload: DeptFeatureGrant = ...,
    db:      AsyncSession     = Depends(get_db),
    caller:  User             = Depends(check_permission("settings.admin")),
):
    tenant_id = tenant_id_ctx.get()
    await db.execute(
        text("""
            INSERT INTO department_feature_grants
                (id, tenant_id, department_id, feature_key, min_role_level, granted_by)
            VALUES (gen_random_uuid(), :tenant_id, :dept_id, :feature_key, :min_role_level, :granted_by)
            ON CONFLICT (tenant_id, department_id, feature_key)
            DO UPDATE SET min_role_level = EXCLUDED.min_role_level
        """),
        {
            "tenant_id":     str(tenant_id),
            "dept_id":       str(dept_id),
            "feature_key":   payload.feature_key,
            "min_role_level": payload.min_role_level,
            "granted_by":    str(caller.id),
        },
    )
    return {"success": True, "message": f"Feature '{payload.feature_key}' granted to department."}


@router.delete("/departments/{dept_id}/features/{feature_key}", status_code=204)
async def revoke_dept_feature(
    dept_id:     uuid.UUID   = Path(...),
    feature_key: str         = Path(...),
    db:          AsyncSession = Depends(get_db),
    caller:      User         = Depends(check_permission("settings.admin")),
):
    tenant_id = tenant_id_ctx.get()
    await db.execute(
        text("""
            DELETE FROM department_feature_grants
            WHERE tenant_id = :tenant_id AND department_id = :dept_id AND feature_key = :feature_key
        """),
        {"tenant_id": str(tenant_id), "dept_id": str(dept_id), "feature_key": feature_key},
    )


# ── Roles ─────────────────────────────────────────────────────

@router.get("/roles")
async def list_roles(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(get_current_user),
):
    rows = (await db.execute(
        text("SELECT id, name, level, is_system_role, description FROM roles ORDER BY level DESC")
    )).fetchall()
    return {
        "success": True,
        "data": [
            {
                "id":            str(r[0]),
                "name":          r[1],
                "level":         r[2],
                "is_system_role": r[3],
                "description":   r[4],
            }
            for r in rows
        ],
    }


@router.post("/roles", status_code=201)
async def create_custom_role(
    payload: RoleCreate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    tenant_id = tenant_id_ctx.get()
    if payload.level >= 5:
        raise HTTPException(
            status_code=422,
            detail="Cannot create custom role at Admin level (5). Modify the Admin role instead.",
        )
    row = await db.execute(
        text("""
            INSERT INTO roles (id, tenant_id, name, level, is_system_role, description)
            VALUES (gen_random_uuid(), :tenant_id, :name, :level, false, :description)
            RETURNING id, name, level
        """),
        {
            "tenant_id":   str(tenant_id),
            "name":        payload.name,
            "level":       payload.level,
            "description": payload.description,
        },
    )
    r = row.fetchone()
    return {"success": True, "data": {"id": str(r[0]), "name": r[1], "level": r[2]}}


# ── Regions ───────────────────────────────────────────────────

@router.get("/regions")
async def list_regions_settings(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(get_current_user),
):
    rows = (await db.execute(
        select(Region).order_by(Region.name)
    )).scalars().all()
    return {
        "success": True,
        "data": [
            {"id": str(r.id), "name": r.name, "code": r.code, "parent_id": str(r.parent_id) if r.parent_id else None}
            for r in rows
        ],
    }


@router.post("/regions", status_code=201)
async def create_region(
    payload: RegionCreate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    tenant_id = tenant_id_ctx.get()
    region = Region(
        tenant_id=tenant_id,
        name=payload.name,
        code=payload.code,
        parent_id=payload.parent_id,
    )
    db.add(region)
    await db.flush()
    return {"success": True, "data": {"id": str(region.id), "name": region.name, "code": region.code}}


# ── Feature Permissions (global list) ────────────────────────

@router.get("/feature-permissions")
async def list_feature_permissions(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(get_current_user),
):
    rows = (await db.execute(
        text("SELECT feature_key, feature_label, module, description FROM feature_permissions ORDER BY module, feature_key")
    )).fetchall()
    return {
        "success": True,
        "data": [
            {
                "feature_key":   r[0],
                "feature_label": r[1],
                "module":        r[2],
                "description":   r[3],
            }
            for r in rows
        ],
    }


# ── Organisation Brand ────────────────────────────────────────

@router.patch("/organisation/brand")
async def update_org_brand(
    payload: OrgBrandUpdate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    tenant_id = tenant_id_ctx.get()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant context.")

    brand: dict = {}
    if payload.primary_color   is not None: brand["primary_color"]   = payload.primary_color
    if payload.logo_url        is not None: brand["logo_url"]        = payload.logo_url
    if payload.favicon_url     is not None: brand["favicon_url"]     = payload.favicon_url
    if payload.company_tagline is not None: brand["company_tagline"] = payload.company_tagline

    if brand:
        import json
        await db.execute(
            text("UPDATE tenants SET settings = settings || jsonb_build_object('brand', (COALESCE(settings->'brand','{}')::jsonb || :brand::jsonb)) WHERE id = :id"),
            {"brand": json.dumps(brand), "id": str(tenant_id)},
        )
    return {"success": True, "message": "Brand settings updated."}


# ── Pipeline Templates ────────────────────────────────────────

def _pipeline_dict(t: PipelineTemplate) -> dict:
    return {
        "id":          str(t.id),
        "name":        t.name,
        "description": t.description,
        "is_active":   t.is_active,
        "created_at":  t.created_at.isoformat(),
        "stages": [
            {
                "id":                     str(s.id),
                "stage_order":            s.stage_order,
                "stage_name":             s.stage_name,
                "department_id":          str(s.department_id),
                "is_required":            s.is_required,
                "is_parallel":            s.is_parallel,
                "expected_duration_days": s.expected_duration_days,
            }
            for s in (t.stages or [])
        ],
    }


@router.get("/pipelines")
async def list_pipelines(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("settings.admin")),
):
    rows = (await db.execute(
        select(PipelineTemplate)
        .where(PipelineTemplate.tenant_id == caller.tenant_id)
        .options(selectinload(PipelineTemplate.stages))
        .order_by(PipelineTemplate.created_at)
    )).scalars().all()
    return {"success": True, "data": [_pipeline_dict(t) for t in rows]}


@router.post("/pipelines", status_code=201)
async def create_pipeline(
    payload: PipelineCreate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    tenant_id = tenant_id_ctx.get()
    t = PipelineTemplate(
        tenant_id=tenant_id,
        name=payload.name,
        description=payload.description,
        created_by=caller.id,
    )
    db.add(t)
    await db.flush()
    await db.refresh(t, attribute_names=["stages"])
    await db.commit()
    return {"success": True, "data": _pipeline_dict(t)}


@router.put("/pipelines/{template_id}/stages")
async def update_pipeline_stages(
    template_id: uuid.UUID          = Path(...),
    payload:     PipelineStagesUpdate = ...,
    db:          AsyncSession       = Depends(get_db),
    caller:      User               = Depends(check_permission("settings.admin")),
):
    t = (await db.execute(
        select(PipelineTemplate).where(PipelineTemplate.id == template_id)
    )).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Pipeline template not found.")

    await db.execute(
        delete(PipelineTemplateStage).where(PipelineTemplateStage.template_id == template_id)
    )
    for s in payload.stages:
        db.add(PipelineTemplateStage(
            template_id=template_id,
            stage_order=s.stage_order,
            stage_name=s.stage_name,
            department_id=s.department_id,
            is_required=s.is_required,
            is_parallel=s.is_parallel,
            expected_duration_days=s.expected_duration_days,
        ))

    await db.flush()
    await db.commit()
    t = (await db.execute(
        select(PipelineTemplate)
        .where(PipelineTemplate.id == template_id)
        .options(selectinload(PipelineTemplate.stages))
    )).scalar_one_or_none()
    return {"success": True, "data": _pipeline_dict(t)}


# ── Integrations ──────────────────────────────────────────────

AVAILABLE_INTEGRATIONS = [
    # ── Communication (5) ──────────────────────────────────────
    {"key": "slack",        "name": "Slack",        "category": "communication", "status": "available",   "description": "Send Opsyn alerts and notifications to Slack channels."},
    {"key": "teams",        "name": "MS Teams",     "category": "communication", "status": "available",   "description": "Push outage and task notifications to Microsoft Teams."},
    {"key": "whatsapp",     "name": "WhatsApp",     "category": "communication", "status": "coming_soon", "description": "Send SMS and WhatsApp alerts via Twilio to field teams."},
    {"key": "sms_twilio",   "name": "SMS (Twilio)", "category": "communication", "status": "available",   "description": "Deliver outage notifications via Twilio SMS to subscribers."},
    {"key": "email_smtp",   "name": "Custom SMTP",  "category": "communication", "status": "available",   "description": "Use your own SMTP server for all transactional emails."},
    # ── Project / Workflow (4) ─────────────────────────────────
    {"key": "jira",         "name": "Jira",         "category": "project",       "status": "coming_soon", "description": "Bi-directional task sync with Jira issues and epics."},
    {"key": "trello",       "name": "Trello",        "category": "project",       "status": "coming_soon", "description": "Mirror Opsyn tasks to Trello boards and cards."},
    {"key": "asana",        "name": "Asana",         "category": "project",       "status": "coming_soon", "description": "Sync project milestones and tasks with Asana workspaces."},
    {"key": "clickup",      "name": "ClickUp",       "category": "project",       "status": "coming_soon", "description": "Push Opsyn tasks and pipelines to ClickUp spaces."},
    # ── Cloud Storage (4) ──────────────────────────────────────
    {"key": "google_drive", "name": "Google Drive",  "category": "cloud_storage", "status": "coming_soon", "description": "Attach and sync documents and survey data with Google Drive."},
    {"key": "onedrive",     "name": "OneDrive",      "category": "cloud_storage", "status": "coming_soon", "description": "Store and retrieve project files from Microsoft OneDrive."},
    {"key": "dropbox",      "name": "Dropbox",       "category": "cloud_storage", "status": "coming_soon", "description": "Link Dropbox folders for media and report storage."},
    {"key": "aws_s3",       "name": "AWS S3",        "category": "cloud_storage", "status": "coming_soon", "description": "Archive reports and survey data to Amazon S3 buckets."},
    # ── Mapping / GIS (4) ─────────────────────────────────────
    {"key": "google_maps",  "name": "Google Maps",   "category": "gis",           "status": "available",   "description": "Infrastructure site mapping and fibre route visualisation."},
    {"key": "mapbox",       "name": "Mapbox",        "category": "gis",           "status": "coming_soon", "description": "Custom styled maps for field operations and coverage overlays."},
    {"key": "qgis",         "name": "QGIS",          "category": "gis",           "status": "coming_soon", "description": "Import and export QGIS project layers for network planning."},
    {"key": "geoserver",    "name": "GeoServer",     "category": "gis",           "status": "coming_soon", "description": "Serve WMS/WFS layers from your GeoServer instance."},
    # ── Telecom (3) ────────────────────────────────────────────
    {"key": "smartolt",     "name": "SmartOLT",      "category": "telecom",       "status": "available",   "description": "Real-time OLT alarm polling and SLA monitoring via SmartOLT."},
    {"key": "fiber_planner","name": "Fiber Planner",  "category": "telecom",       "status": "coming_soon", "description": "Import fibre route plans and splitter inventory from Fiber Planner."},
    {"key": "netconf",      "name": "NETCONF/YANG",  "category": "telecom",       "status": "coming_soon", "description": "Telemetry streaming from network devices via NETCONF/YANG."},
    # ── Alerting (3) ───────────────────────────────────────────
    {"key": "pagerduty",    "name": "PagerDuty",     "category": "alerting",      "status": "available",   "description": "Route outage alerts to PagerDuty on-call schedules."},
    {"key": "opsgenie",     "name": "OpsGenie",      "category": "alerting",      "status": "coming_soon", "description": "Manage on-call escalations and alert routing via OpsGenie."},
    {"key": "webhook",      "name": "Webhooks",      "category": "alerting",      "status": "available",   "description": "POST signed events to any external URL on key Opsyn actions."},
    # ── AI & Intelligence (2) ─────────────────────────────────
    {"key": "ai_assistant", "name": "AI Assistant",  "category": "ai",            "status": "coming_soon", "description": "GPT-powered root cause analysis and incident recommendation engine."},
    {"key": "ai_reports",   "name": "AI Auto-Reports","category": "ai",           "status": "coming_soon", "description": "Automated weekly executive reports generated by AI."},
    # ── Auth / Security (2) ───────────────────────────────────
    {"key": "sso_saml",     "name": "SAML SSO",      "category": "auth",          "status": "coming_soon", "description": "Enterprise SSO via Okta, Azure AD, or any SAML 2.0 identity provider."},
    {"key": "sso_oidc",     "name": "OpenID Connect","category": "auth",          "status": "coming_soon", "description": "Enterprise SSO via Google, Azure AD, or any OpenID Connect provider."},
]


@router.get("/integrations")
async def list_integrations(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(get_current_user),  # all authenticated users can list integrations
):
    enabled_keys: set = set()
    tenant_id = tenant_id_ctx.get()
    if tenant_id is not None:
        try:
            row = (await db.execute(
                text("SELECT settings FROM tenants WHERE id = :id"),
                {"id": str(tenant_id)},
            )).fetchone()
            tenant_settings = (row[0] or {}) if row else {}
            enabled_keys = set((tenant_settings.get("integrations") or {}).keys())
        except Exception:
            pass  # DB error — return static list with all integrations disabled

    data = [
        {**i, "enabled": i["key"] in enabled_keys}
        for i in AVAILABLE_INTEGRATIONS
    ]
    return {"success": True, "data": data}


# ── SmartOLT Integration ──────────────────────────────────────

class SmartOLTConfigUpdate(BaseModel):
    api_key:               Optional[str]   = None
    api_url:               Optional[str]   = None
    webhook_secret:        Optional[str]   = None
    polling_enabled:       Optional[bool]  = None
    polling_interval_secs: Optional[int]   = None
    severity_thresholds:   Optional[dict]  = None


class OltMapCreate(BaseModel):
    smartolt_olt_id: str
    olt_name:        Optional[str]   = None
    region_id:       Optional[uuid.UUID] = None
    latitude:        Optional[float] = None
    longitude:       Optional[float] = None


def _cfg_dict(c) -> dict:
    return {
        "id":                    str(c.id),
        "api_url":               c.api_url,
        "polling_enabled":       c.polling_enabled,
        "polling_interval_secs": c.polling_interval_secs,
        "severity_thresholds":   c.severity_thresholds,
        "has_api_key":           bool(c.api_key),
        "has_webhook_secret":    bool(c.webhook_secret),
        "updated_at":            c.updated_at.isoformat() if c.updated_at else None,
    }


@router.get("/integrations/smartolt")
async def get_smartolt_config(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("settings.admin")),
):
    from app.modules.smartolt.models import SmartOLTConfig
    tenant_id = caller.tenant_id
    cfg = (await db.execute(
        select(SmartOLTConfig).where(SmartOLTConfig.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not cfg:
        return {"success": True, "data": None}
    return {"success": True, "data": _cfg_dict(cfg)}


@router.post("/integrations/smartolt", status_code=201)
async def create_smartolt_config(
    payload: SmartOLTConfigUpdate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    from app.modules.smartolt.models import SmartOLTConfig
    tenant_id = caller.tenant_id
    existing = (await db.execute(
        select(SmartOLTConfig).where(SmartOLTConfig.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "SmartOLT config already exists — use PATCH to update.")
    cfg = SmartOLTConfig(
        tenant_id             = tenant_id,
        api_key               = payload.api_key,
        api_url               = payload.api_url or "https://app.smartolt.com",
        webhook_secret        = payload.webhook_secret,
        polling_enabled       = payload.polling_enabled or False,
        polling_interval_secs = payload.polling_interval_secs or 60,
        severity_thresholds   = payload.severity_thresholds or {"warning": 10, "high": 50, "critical": 200},
    )
    db.add(cfg)
    await db.flush()
    await db.commit()
    return {"success": True, "data": _cfg_dict(cfg)}


@router.patch("/integrations/smartolt")
async def update_smartolt_config(
    payload: SmartOLTConfigUpdate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    from app.modules.smartolt.models import SmartOLTConfig
    from datetime import datetime as _dt, timezone as _tz
    tenant_id = caller.tenant_id
    cfg = (await db.execute(
        select(SmartOLTConfig).where(SmartOLTConfig.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not cfg:
        raise HTTPException(404, "SmartOLT config not found — use POST to create.")
    if payload.api_key               is not None: cfg.api_key               = payload.api_key
    if payload.api_url               is not None: cfg.api_url               = payload.api_url
    if payload.webhook_secret        is not None: cfg.webhook_secret        = payload.webhook_secret
    if payload.polling_enabled       is not None: cfg.polling_enabled       = payload.polling_enabled
    if payload.polling_interval_secs is not None: cfg.polling_interval_secs = payload.polling_interval_secs
    if payload.severity_thresholds   is not None: cfg.severity_thresholds   = payload.severity_thresholds
    cfg.updated_at = _dt.now(_tz.utc)
    await db.flush()
    await db.commit()
    return {"success": True, "data": _cfg_dict(cfg)}


@router.get("/integrations/smartolt/olt-map")
async def list_olt_map(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("settings.admin")),
):
    from app.modules.smartolt.models import SmartOLTOltMap
    tenant_id = caller.tenant_id
    rows = (await db.execute(
        select(SmartOLTOltMap).where(SmartOLTOltMap.tenant_id == tenant_id)
    )).scalars().all()
    return {"success": True, "data": [_olt_map_dict(r) for r in rows]}


@router.post("/integrations/smartolt/olt-map", status_code=201)
async def add_olt_mapping(
    payload: OltMapCreate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    from app.modules.smartolt.models import SmartOLTOltMap
    tenant_id = caller.tenant_id
    mapping = SmartOLTOltMap(
        tenant_id       = tenant_id,
        smartolt_olt_id = payload.smartolt_olt_id,
        olt_name        = payload.olt_name,
        region_id       = payload.region_id,
        latitude        = payload.latitude,
        longitude       = payload.longitude,
    )
    db.add(mapping)
    await db.flush()
    await db.commit()
    return {"success": True, "data": _olt_map_dict(mapping)}


@router.delete("/integrations/smartolt/olt-map/{mapping_id}", status_code=204)
async def delete_olt_mapping(
    mapping_id: uuid.UUID = Path(...),
    db:         AsyncSession = Depends(get_db),
    _:          User         = Depends(check_permission("settings.admin")),
):
    from app.modules.smartolt.models import SmartOLTOltMap
    mapping = (await db.execute(
        select(SmartOLTOltMap).where(SmartOLTOltMap.id == mapping_id)
    )).scalar_one_or_none()
    if not mapping:
        raise HTTPException(404, "OLT mapping not found.")
    await db.delete(mapping)
    await db.commit()


def _olt_map_dict(m) -> dict:
    return {
        "id":               str(m.id),
        "smartolt_olt_id":  m.smartolt_olt_id,
        "olt_name":         m.olt_name,
        "region_id":        str(m.region_id) if m.region_id else None,
        "latitude":         m.latitude,
        "longitude":        m.longitude,
        "is_active":        m.is_active,
        "last_synced_at":   m.last_synced_at.isoformat() if m.last_synced_at else None,
    }


# ── Generic Integration Config (Slack, Teams, PagerDuty, SMTP) ──

_CONFIGURABLE = {
    "slack":      ["webhook_url", "channel"],
    "teams":      ["webhook_url"],
    "pagerduty":  ["api_key", "service_id"],
    "email_smtp": ["host", "port", "username", "password", "from_email"],
}
_SENSITIVE = {"api_key", "password"}


class IntegrationConfigSave(BaseModel):
    config: dict


@router.get("/integrations/{key}/config")
async def get_integration_config(
    key: str           = Path(...),
    db:  AsyncSession  = Depends(get_db),
    _:   User          = Depends(check_permission("settings.admin")),
):
    if key not in _CONFIGURABLE:
        raise HTTPException(404, f"Integration '{key}' has no configurable fields.")
    tenant_id = tenant_id_ctx.get()
    row = (await db.execute(
        text("SELECT settings FROM tenants WHERE id = :id"), {"id": str(tenant_id)}
    )).fetchone()
    tenant_settings = (row[0] or {}) if row else {}
    cfg = (tenant_settings.get("integrations") or {}).get(key, {})
    masked = {k: ("••••••" if k in _SENSITIVE and v else v) for k, v in cfg.items()}
    return {"success": True, "data": masked}


@router.post("/integrations/{key}/config")
async def save_integration_config(
    key:     str                    = Path(...),
    payload: IntegrationConfigSave  = ...,
    db:      AsyncSession           = Depends(get_db),
    _:       User                   = Depends(check_permission("settings.admin")),
):
    if key not in _CONFIGURABLE:
        raise HTTPException(404, f"Integration '{key}' has no configurable fields.")
    tenant_id = tenant_id_ctx.get()
    row = (await db.execute(
        text("SELECT settings FROM tenants WHERE id = :id"), {"id": str(tenant_id)}
    )).fetchone()
    tenant_settings = dict(row[0] or {}) if row else {}
    integrations     = dict(tenant_settings.get("integrations") or {})
    existing         = dict(integrations.get(key, {}))
    for k, v in payload.config.items():
        if k in _SENSITIVE and v in ("", "••••••"):
            continue
        existing[k] = v
    integrations[key]             = existing
    tenant_settings["integrations"] = integrations
    await db.execute(
        text("UPDATE tenants SET settings = :s::jsonb WHERE id = :id"),
        {"s": json.dumps(tenant_settings), "id": str(tenant_id)},
    )
    await db.commit()
    return {"success": True, "data": {"key": key, "configured": True}}


@router.delete("/integrations/{key}/config", status_code=204)
async def remove_integration_config(
    key: str          = Path(...),
    db:  AsyncSession = Depends(get_db),
    _:   User         = Depends(check_permission("settings.admin")),
):
    if key not in _CONFIGURABLE:
        raise HTTPException(404, f"Integration '{key}' has no configurable fields.")
    tenant_id = tenant_id_ctx.get()
    row = (await db.execute(
        text("SELECT settings FROM tenants WHERE id = :id"), {"id": str(tenant_id)}
    )).fetchone()
    tenant_settings = dict(row[0] or {}) if row else {}
    integrations     = dict(tenant_settings.get("integrations") or {})
    integrations.pop(key, None)
    tenant_settings["integrations"] = integrations
    await db.execute(
        text("UPDATE tenants SET settings = :s::jsonb WHERE id = :id"),
        {"s": json.dumps(tenant_settings), "id": str(tenant_id)},
    )
    await db.commit()


# ── Outage Notification Rules ─────────────────────────────────

class NotificationRuleCreate(BaseModel):
    name:             str
    min_severity:     str           = "warning"
    min_subscribers:  int           = 0
    channels:         list          = ["sms"]
    message_template: Optional[str] = None
    is_auto:          bool          = False
    is_active:        bool          = True


class NotificationRuleUpdate(BaseModel):
    name:             Optional[str]  = None
    min_severity:     Optional[str]  = None
    min_subscribers:  Optional[int]  = None
    channels:         Optional[list] = None
    message_template: Optional[str]  = None
    is_auto:          Optional[bool] = None
    is_active:        Optional[bool] = None


def _rule_dict(r) -> dict:
    return {
        "id":               str(r.id),
        "name":             r.name,
        "min_severity":     r.min_severity,
        "min_subscribers":  r.min_subscribers,
        "channels":         r.channels,
        "message_template": r.message_template,
        "is_auto":          r.is_auto,
        "is_active":        r.is_active,
        "created_at":       r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/notification-rules")
async def list_notification_rules(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("settings.admin")),
):
    from app.modules.shifts.models import OutageNotificationRule
    rows = (await db.execute(
        select(OutageNotificationRule).where(
            OutageNotificationRule.tenant_id == caller.tenant_id
        ).order_by(OutageNotificationRule.created_at.desc())
    )).scalars().all()
    return {"success": True, "data": [_rule_dict(r) for r in rows]}


@router.post("/notification-rules", status_code=201)
async def create_notification_rule(
    payload: NotificationRuleCreate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    from app.modules.shifts.models import OutageNotificationRule
    rule = OutageNotificationRule(
        tenant_id        = caller.tenant_id,
        name             = payload.name,
        min_severity     = payload.min_severity,
        min_subscribers  = payload.min_subscribers,
        channels         = payload.channels,
        message_template = payload.message_template,
        is_auto          = payload.is_auto,
        is_active        = payload.is_active,
        created_by       = caller.id,
    )
    db.add(rule); await db.flush(); await db.commit()
    return {"success": True, "data": _rule_dict(rule)}


@router.patch("/notification-rules/{rule_id}")
async def update_notification_rule(
    rule_id: uuid.UUID          = Path(...),
    payload: NotificationRuleUpdate = ...,
    db:      AsyncSession       = Depends(get_db),
    caller:  User               = Depends(check_permission("settings.admin")),
):
    from app.modules.shifts.models import OutageNotificationRule
    rule = (await db.execute(
        select(OutageNotificationRule).where(OutageNotificationRule.id == rule_id)
    )).scalar_one_or_none()
    if not rule: raise HTTPException(404, "Rule not found.")
    if payload.name             is not None: rule.name             = payload.name
    if payload.min_severity     is not None: rule.min_severity     = payload.min_severity
    if payload.min_subscribers  is not None: rule.min_subscribers  = payload.min_subscribers
    if payload.channels         is not None: rule.channels         = payload.channels
    if payload.message_template is not None: rule.message_template = payload.message_template
    if payload.is_auto          is not None: rule.is_auto          = payload.is_auto
    if payload.is_active        is not None: rule.is_active        = payload.is_active
    await db.flush(); await db.commit()
    return {"success": True, "data": _rule_dict(rule)}


@router.delete("/notification-rules/{rule_id}", status_code=204)
async def delete_notification_rule(
    rule_id: uuid.UUID    = Path(...),
    db:      AsyncSession = Depends(get_db),
    _:       User         = Depends(check_permission("settings.admin")),
):
    from app.modules.shifts.models import OutageNotificationRule
    rule = (await db.execute(
        select(OutageNotificationRule).where(OutageNotificationRule.id == rule_id)
    )).scalar_one_or_none()
    if not rule: raise HTTPException(404, "Rule not found.")
    await db.delete(rule); await db.commit()


@router.post("/notification-rules/{rule_id}/test", status_code=202)
async def test_notification_rule(
    rule_id: uuid.UUID    = Path(...),
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    from app.modules.shifts.models import OutageNotificationRule
    rule = (await db.execute(
        select(OutageNotificationRule).where(OutageNotificationRule.id == rule_id)
    )).scalar_one_or_none()
    if not rule: raise HTTPException(404, "Rule not found.")
    # Fire a test notification via Celery
    from app.core.celery_app import celery_app as _celery
    _celery.send_task(
        "notifications.send_outage_notifications",
        args=["00000000-0000-0000-0000-000000000000", str(caller.tenant_id)],
    )
    return {"success": True, "data": {"message": "Test notification queued.", "channels": rule.channels}}


# ── Infrastructure Monitoring Config ─────────────────────────

class MonitoringConfigCreate(BaseModel):
    entity_type:            str
    entity_id:              uuid.UUID
    warn_threshold_pct:     int = 70
    critical_threshold_pct: int = 90
    check_interval_minutes: int = 15
    alert_channels:         list = []
    assigned_role_level:    int = 2
    is_active:              bool = True


class MonitoringConfigUpdate(BaseModel):
    warn_threshold_pct:     Optional[int]  = None
    critical_threshold_pct: Optional[int]  = None
    check_interval_minutes: Optional[int]  = None
    alert_channels:         Optional[list] = None
    assigned_role_level:    Optional[int]  = None
    is_active:              Optional[bool] = None


class AlertRuleCreate(BaseModel):
    name:            str
    condition_field: str
    operator:        str  = "gt"
    threshold_value: float
    severity:        str  = "warning"
    action_type:     str  = "notify"
    action_params:   dict = {}
    is_active:       bool = True


class AlertRuleUpdate(BaseModel):
    name:            Optional[str]   = None
    condition_field: Optional[str]   = None
    operator:        Optional[str]   = None
    threshold_value: Optional[float] = None
    severity:        Optional[str]   = None
    action_type:     Optional[str]   = None
    action_params:   Optional[dict]  = None
    is_active:       Optional[bool]  = None


def _mon_config_dict(c) -> dict:
    return {
        "id": str(c.id), "entity_type": c.entity_type, "entity_id": str(c.entity_id),
        "warn_threshold_pct": c.warn_threshold_pct,
        "critical_threshold_pct": c.critical_threshold_pct,
        "check_interval_minutes": c.check_interval_minutes,
        "alert_channels": c.alert_channels or [],
        "assigned_role_level": c.assigned_role_level,
        "is_active": c.is_active,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


def _alert_rule_dict(r) -> dict:
    return {
        "id": str(r.id), "name": r.name,
        "condition_field": r.condition_field, "operator": r.operator,
        "threshold_value": float(r.threshold_value), "severity": r.severity,
        "action_type": r.action_type, "action_params": r.action_params or {},
        "is_active": r.is_active, "created_at": r.created_at.isoformat(),
    }


@router.get("/infrastructure/monitoring")
async def list_monitoring_configs(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("infrastructure.view")),
):
    from app.modules.infrastructure.models import InfraMonitoringConfig
    rows = (await db.execute(
        select(InfraMonitoringConfig).where(InfraMonitoringConfig.tenant_id == caller.tenant_id)
    )).scalars().all()
    return {"success": True, "data": [_mon_config_dict(r) for r in rows]}


@router.post("/infrastructure/monitoring", status_code=201)
async def create_monitoring_config(
    payload: MonitoringConfigCreate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.edit")),
):
    from app.modules.infrastructure.models import InfraMonitoringConfig
    cfg = InfraMonitoringConfig(tenant_id=caller.tenant_id, **payload.model_dump())
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    return {"success": True, "data": _mon_config_dict(cfg)}


@router.put("/infrastructure/monitoring/{config_id}")
async def update_monitoring_config(
    config_id: uuid.UUID      = Path(...),
    payload:   MonitoringConfigUpdate = ...,
    db:        AsyncSession   = Depends(get_db),
    caller:    User           = Depends(check_permission("infrastructure.edit")),
):
    from app.modules.infrastructure.models import InfraMonitoringConfig
    cfg = await db.get(InfraMonitoringConfig, config_id)
    if not cfg or cfg.tenant_id != caller.tenant_id:
        raise HTTPException(404, "Monitoring config not found.")
    for field, val in payload.model_dump(exclude_unset=True).items():
        setattr(cfg, field, val)
    await db.commit()
    await db.refresh(cfg)
    return {"success": True, "data": _mon_config_dict(cfg)}


@router.delete("/infrastructure/monitoring/{config_id}", status_code=204)
async def delete_monitoring_config(
    config_id: uuid.UUID    = Path(...),
    db:        AsyncSession = Depends(get_db),
    caller:    User         = Depends(check_permission("infrastructure.edit")),
):
    from app.modules.infrastructure.models import InfraMonitoringConfig
    cfg = await db.get(InfraMonitoringConfig, config_id)
    if not cfg or cfg.tenant_id != caller.tenant_id:
        raise HTTPException(404, "Monitoring config not found.")
    await db.delete(cfg)
    await db.commit()


@router.get("/infrastructure/alert-rules")
async def list_alert_rules(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("infrastructure.view")),
):
    from app.modules.infrastructure.models import InfraAlertRule
    rows = (await db.execute(
        select(InfraAlertRule).where(InfraAlertRule.tenant_id == caller.tenant_id)
    )).scalars().all()
    return {"success": True, "data": [_alert_rule_dict(r) for r in rows]}


@router.post("/infrastructure/alert-rules", status_code=201)
async def create_alert_rule(
    payload: AlertRuleCreate,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.edit")),
):
    from app.modules.infrastructure.models import InfraAlertRule
    rule = InfraAlertRule(tenant_id=caller.tenant_id, **payload.model_dump())
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return {"success": True, "data": _alert_rule_dict(rule)}


@router.put("/infrastructure/alert-rules/{rule_id}")
async def update_alert_rule(
    rule_id: uuid.UUID      = Path(...),
    payload: AlertRuleUpdate = ...,
    db:      AsyncSession   = Depends(get_db),
    caller:  User           = Depends(check_permission("infrastructure.edit")),
):
    from app.modules.infrastructure.models import InfraAlertRule
    rule = await db.get(InfraAlertRule, rule_id)
    if not rule or rule.tenant_id != caller.tenant_id:
        raise HTTPException(404, "Alert rule not found.")
    for field, val in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, val)
    await db.commit()
    await db.refresh(rule)
    return {"success": True, "data": _alert_rule_dict(rule)}


@router.delete("/infrastructure/alert-rules/{rule_id}", status_code=204)
async def delete_alert_rule(
    rule_id: uuid.UUID    = Path(...),
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("infrastructure.edit")),
):
    from app.modules.infrastructure.models import InfraAlertRule
    rule = await db.get(InfraAlertRule, rule_id)
    if not rule or rule.tenant_id != caller.tenant_id:
        raise HTTPException(404, "Alert rule not found.")
    await db.delete(rule)
    await db.commit()
