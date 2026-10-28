# ============================================================
# OPSYN ALL DOMAIN MODULES — app/modules/all_modules.py
# Organisation · Roles · Outage · Onboarding · Notifications
# Projects · Reports · Permissions
# Fixed: __allow_unmapped__ on all models, correct FK declarations
# ============================================================

from __future__ import annotations
import uuid, datetime, csv, io
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, String, Text, Boolean, Integer, ForeignKey, DateTime, cast
from sqlalchemy.dialects.postgresql import JSONB as PgJSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from fastapi import APIRouter, Depends, Query, Path, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from app.core.database import Base, get_db
from app.core.context import tenant_id_ctx
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import check_permission
from app.modules.organisation.models import Department, Team, Region
from app.modules.projects.models import Project
from app.modules.staff.models import User, StaffProfile
from app.modules.tasks.models import Task  # noqa: F401 — registers tasks table in SA metadata

SP = StaffProfile  # module-level alias used throughout report queries
from app.modules.projects.pipeline_service import (
    start_pipeline, start_graph_pipeline, advance_stage, push_back_stage,
    add_stage_comment, approve_stage, get_pipeline, get_all_templates, create_template,
)
from app.modules.projects.schemas import (
    AdvanceStageRequest, PushBackRequest, StageCommentCreate, PipelineTemplateCreate
)


class OrgRequest(BaseModel):
    name: str
    head_user_id:  Optional[uuid.UUID] = None
    parent_id:     Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None
    lead_user_id:  Optional[uuid.UUID] = None
    code:          Optional[str] = None


router_org = APIRouter()

@router_org.get("/departments")
async def list_departments(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(Department).order_by(Department.name))).scalars().all()
    return {"success": True, "data": [{"id": str(d.id), "name": d.name} for d in rows]}

@router_org.post("/departments", status_code=201)
async def create_department(p: OrgRequest, db: AsyncSession = Depends(get_db),
                             _: User = Depends(check_permission("settings.admin"))):
    # tenant_id is NOT NULL. Omitting it made every call to this endpoint
    # fail with NotNullViolationError and return 500, so no department
    # could be created through /api/v1/departments at all. The equivalent
    # handler in settings/router.py already sets it this way.
    d = Department(
        tenant_id=tenant_id_ctx.get(),
        name=p.name, head_user_id=p.head_user_id, parent_id=p.parent_id,
    )
    db.add(d); await db.flush()
    return {"success": True, "data": {"id": str(d.id), "name": d.name}}

@router_org.get("/teams")
async def list_teams(department_id: Optional[uuid.UUID] = None,
                     db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    q = select(Team).order_by(Team.name)
    if department_id: q = q.where(Team.department_id == department_id)
    rows = (await db.execute(q)).scalars().all()
    return {"success": True, "data": [{"id": str(t.id), "name": t.name,
             "department_id": str(t.department_id)} for t in rows]}

@router_org.post("/teams", status_code=201)
async def create_team(p: OrgRequest, db: AsyncSession = Depends(get_db),
                       _: User = Depends(check_permission("settings.admin"))):
    t = Team(name=p.name, department_id=p.department_id, lead_user_id=p.lead_user_id)
    db.add(t); await db.flush()
    return {"success": True, "data": {"id": str(t.id), "name": t.name}}

@router_org.get("/regions")
async def list_regions(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await db.execute(select(Region).order_by(Region.name))).scalars().all()
    return {"success": True, "data": [{"id": str(r.id), "name": r.name, "code": r.code} for r in rows]}


# ══════════════════════════════════════════════════════════════
#  ROLES & PERMISSIONS
# ══════════════════════════════════════════════════════════════

class Role(Base):
    __tablename__      = "roles"
    __allow_unmapped__ = True
    id:             Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:      Mapped[uuid.UUID]        = mapped_column(ForeignKey("tenants.id"), nullable=False)
    name:           Mapped[str]              = mapped_column(String(80), nullable=False)
    level:          Mapped[int]              = mapped_column(Integer, nullable=False)
    is_system_role: Mapped[bool]             = mapped_column(Boolean, default=False)
    description:    Mapped[str | None]       = mapped_column(Text)
    users:          list                     = relationship("User", back_populates="role")


class UserScope(Base):
    __tablename__      = "user_scopes"
    __allow_unmapped__ = True
    id:                 Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:          Mapped[uuid.UUID]        = mapped_column(ForeignKey("tenants.id"), nullable=False)
    user_id:            Mapped[uuid.UUID]        = mapped_column(ForeignKey("users.id"), nullable=False)
    scope_type:         Mapped[str]              = mapped_column(String(20))
    scope_reference_id: Mapped[uuid.UUID]
    granted_by:         Mapped[uuid.UUID]        = mapped_column(ForeignKey("users.id"))
    created_at:         Mapped[datetime.datetime]= mapped_column(default=datetime.datetime.utcnow)
    user:               "User" = relationship("User", back_populates="scopes", foreign_keys=[user_id])


class UserRoleHistory(Base):
    __tablename__      = "user_role_history"
    __allow_unmapped__ = True
    id:          Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id:     Mapped[uuid.UUID]        = mapped_column(ForeignKey("users.id"))
    old_role_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("roles.id"))
    new_role_id: Mapped[uuid.UUID]        = mapped_column(ForeignKey("roles.id"))
    changed_by:  Mapped[uuid.UUID]        = mapped_column(ForeignKey("users.id"))
    changed_at:  Mapped[datetime.datetime]= mapped_column(default=datetime.datetime.utcnow)


class RoleCreateRequest(BaseModel):
    name: str; level: int; description: Optional[str] = None

class AssignRoleRequest(BaseModel):
    user_id: uuid.UUID

class AssignScopeRequest(BaseModel):
    user_id: uuid.UUID; scope_type: str; scope_reference_id: uuid.UUID


router_roles = APIRouter()

@router_roles.get("/roles")
async def list_roles(assignable: Optional[bool] = None,
                     db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    q = select(Role).order_by(Role.level.desc())
    if assignable: q = q.where(Role.level < caller.role.level)
    rows = (await db.execute(q)).scalars().all()
    return {"success": True, "data": [{"id": str(r.id), "name": r.name, "level": r.level,
             "is_system_role": r.is_system_role} for r in rows]}

@router_roles.post("/roles", status_code=201)
async def create_role(p: RoleCreateRequest, db: AsyncSession = Depends(get_db),
                       _: User = Depends(check_permission("settings.admin"))):
    r = Role(name=p.name, level=p.level, description=p.description)
    db.add(r); await db.flush()
    return {"success": True, "data": {"id": str(r.id), "name": r.name, "level": r.level}}

@router_roles.post("/roles/{role_id}/assign")
async def assign_role(role_id: uuid.UUID = Path(...), req: AssignRoleRequest = ...,
                       db: AsyncSession = Depends(get_db), caller: User = Depends(check_permission("settings.admin"))):
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if not role: raise HTTPException(404, "Role not found.")
    if role.level >= caller.role.level: raise HTTPException(403, "Cannot assign role at or above your level.")
    user = (await db.execute(select(User).where(User.id == req.user_id))).scalar_one_or_none()
    if not user: raise HTTPException(404, "User not found.")
    db.add(UserRoleHistory(user_id=user.id, old_role_id=user.role_id,
                            new_role_id=role.id, changed_by=caller.id))
    user.role_id = role.id; await db.flush()
    return {"success": True, "data": {"user_id": str(user.id), "new_role": role.name}}

@router_roles.get("/user-scopes/{user_id}")
async def get_user_scopes(user_id: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db),
                           _: User = Depends(check_permission("settings.admin"))):
    scopes = (await db.execute(select(UserScope).where(UserScope.user_id == user_id))).scalars().all()
    return {"success": True, "data": [{"id": str(s.id), "scope_type": s.scope_type,
             "scope_reference_id": str(s.scope_reference_id)} for s in scopes]}

@router_roles.post("/user-scopes", status_code=201)
async def grant_scope(req: AssignScopeRequest, db: AsyncSession = Depends(get_db),
                       caller: User = Depends(check_permission("settings.admin"))):
    s = UserScope(user_id=req.user_id, scope_type=req.scope_type,
                   scope_reference_id=req.scope_reference_id, granted_by=caller.id)
    db.add(s); await db.flush()
    return {"success": True, "data": {"id": str(s.id)}}

@router_roles.delete("/user-scopes/{scope_id}")
async def revoke_scope(scope_id: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db),
                        _: User = Depends(check_permission("settings.admin"))):
    s = (await db.execute(select(UserScope).where(UserScope.id == scope_id))).scalar_one_or_none()
    if not s: raise HTTPException(404, "Scope not found.")
    await db.delete(s)
    return {"success": True, "message": "Scope revoked."}


# ══════════════════════════════════════════════════════════════
#  OUTAGE
# ══════════════════════════════════════════════════════════════

class OutageIncident(Base):
    __tablename__      = "outage_incidents"
    __allow_unmapped__ = True
    id:                    Mapped[uuid.UUID]               = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:             Mapped[uuid.UUID]               = mapped_column(ForeignKey("tenants.id"), nullable=False)
    reference:             Mapped[str]                     = mapped_column(String(20), unique=True)
    title:                 Mapped[str]                     = mapped_column(String(200), nullable=False)
    description:           Mapped[str | None]              = mapped_column(Text)
    severity:              Mapped[str]                     = mapped_column(String(20), default="warning")
    status:                Mapped[str]                     = mapped_column(String(20), default="active")
    region_id:             Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("regions.id"))
    olt_reference:         Mapped[str | None]              = mapped_column(String(100))
    reported_by:           Mapped[uuid.UUID]               = mapped_column(ForeignKey("users.id"))
    resolved_at:           Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at:            Mapped[datetime.datetime]       = mapped_column(default=datetime.datetime.utcnow)
    updated_at:            Mapped[datetime.datetime]       = mapped_column(
        default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    # S3.4 SmartOLT columns
    source:                Mapped[str]                     = mapped_column(String(20), default="manual")
    smartolt_event_id:     Mapped[str | None]              = mapped_column(String(100))
    affected_customer_ids: Mapped[list | None]             = mapped_column(PgJSONB)
    affected_subscribers:  Mapped[int]                     = mapped_column(Integer, default=0)
    sla_deadline:          Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    breached_sla:          Mapped[bool]                    = mapped_column(Boolean, default=False)
    linked_task_id:        Mapped[uuid.UUID | None]        = mapped_column(ForeignKey("tasks.id"))


class LogOutageRequest(BaseModel):
    title: str; severity: str = "warning"
    description: Optional[str] = None
    region_id: Optional[uuid.UUID] = None
    olt_reference: Optional[str] = None
    affected_subscribers: int = 0


router_outage = APIRouter()

async def _next_ref(db: AsyncSession) -> str:
    n = (await db.execute(select(func.count()).select_from(OutageIncident))).scalar_one()
    return f"OUT-{datetime.date.today().year}-{str(n+1).zfill(3)}"

@router_outage.get("")
async def list_outages(status: Optional[str] = Query(None),
                        severity: Optional[str] = None,
                        db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    q = select(OutageIncident).order_by(OutageIncident.created_at.desc())
    if status:   q = q.where(OutageIncident.status == status)
    if severity: q = q.where(OutageIncident.severity == severity)
    rows = (await db.execute(q)).scalars().all()
    return {"success": True, "data": {"items": [_out(o) for o in rows], "total": len(rows)}}

@router_outage.post("", status_code=201)
async def log_outage(p: LogOutageRequest, db: AsyncSession = Depends(get_db),
                      caller: User = Depends(check_permission("outage.log"))):
    import datetime as _dt
    sla_map = {"critical": 60, "high": 180, "warning": 480, "low": 1440}
    sla_mins = sla_map.get(p.severity, 480)
    inc = OutageIncident(
        reference            = await _next_ref(db),
        title                = p.title,
        description          = p.description,
        severity             = p.severity,
        region_id            = p.region_id,
        olt_reference        = p.olt_reference,
        reported_by          = caller.id,
        source               = "manual",
        affected_subscribers = p.affected_subscribers,
        sla_deadline         = _dt.datetime.utcnow() + _dt.timedelta(minutes=sla_mins),
        breached_sla         = False,
        tenant_id            = caller.tenant_id,
    )
    db.add(inc); await db.flush()
    from app.events.bus import event_bus
    await event_bus.emit("outage.logged", {
        "incident_id": str(inc.id),
        "title":       inc.title,
        "severity":    inc.severity,
        "reported_by": str(caller.id),
    })
    from app.core.celery_app import celery_app as _celery
    _celery.send_task(
        "notifications.send_outage_notifications",
        args=[str(inc.id), str(inc.tenant_id)],
    )
    return {"success": True, "data": _out(inc)}

@router_outage.patch("/{iid}/resolve")
async def resolve_outage(iid: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db),
                          _: User = Depends(check_permission("outage.manage"))):
    inc = (await db.execute(select(OutageIncident).where(OutageIncident.id == iid))).scalar_one_or_none()
    if not inc: raise HTTPException(404, "Incident not found.")
    inc.status = "resolved"; inc.resolved_at = datetime.datetime.utcnow()
    await db.flush()
    return {"success": True, "data": _out(inc)}

@router_outage.get("/{iid}")
async def get_outage_detail(iid: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db),
                             _: User = Depends(get_current_user)):
    inc = (await db.execute(select(OutageIncident).where(OutageIncident.id == iid))).scalar_one_or_none()
    if not inc: raise HTTPException(404, "Incident not found.")
    # Load timeline
    timeline_rows = (await db.execute(
        text("SELECT id, event_type, actor_id, body, meta, created_at FROM activity_timeline WHERE entity_type='outage' AND entity_id=:eid ORDER BY created_at ASC"),
        {"eid": str(iid)},
    )).fetchall()
    timeline = [
        {"id": str(r[0]), "event_type": r[1], "actor_id": str(r[2]) if r[2] else None,
         "body": r[3], "meta": r[4], "created_at": r[5].isoformat() if r[5] else None}
        for r in timeline_rows
    ]
    return {"success": True, "data": {**_out(inc), "timeline": timeline}}

@router_outage.patch("/{iid}")
async def update_outage(iid: uuid.UUID = Path(...), body: dict = ...,
                         db: AsyncSession = Depends(get_db), _: User = Depends(check_permission("outage.manage"))):
    inc = (await db.execute(select(OutageIncident).where(OutageIncident.id == iid))).scalar_one_or_none()
    if not inc: raise HTTPException(404, "Incident not found.")
    if "status" in body: inc.status = body["status"]
    await db.flush()
    return {"success": True, "data": _out(inc)}

@router_outage.post("/{iid}/notify-customers", status_code=202)
async def notify_customers(iid: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db),
                            _: User = Depends(check_permission("outage.manage"))):
    inc = (await db.execute(select(OutageIncident).where(OutageIncident.id == iid))).scalar_one_or_none()
    if not inc: raise HTTPException(404, "Incident not found.")
    # Fire Celery task (customer notification service — S3.5)
    from app.core.celery_app import celery_app
    celery_app.send_task("notifications.send_outage_alert", args=[str(inc.id), inc.title, inc.severity])
    return {"success": True, "data": {"message": "Customer notifications dispatched.", "incident_id": str(inc.id)}}

@router_outage.post("/webhook/smartolt")
async def smartolt_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive signed events from SmartOLT (HMAC-SHA256 via X-SmartOLT-Signature header)."""
    from app.modules.smartolt.models import SmartOLTConfig
    from app.modules.smartolt.handler import handle_smartolt_event, verify_smartolt_signature
    from app.core.context import tenant_id_ctx

    x_tenant    = request.headers.get("X-Webhook-Tenant") or request.headers.get("X-SmartOLT-Tenant")
    x_signature = request.headers.get("X-SmartOLT-Signature") or request.headers.get("X-Webhook-Signature")

    if not x_tenant:
        raise HTTPException(400, "X-Webhook-Tenant header required.")

    try:
        tenant_id = uuid.UUID(x_tenant)
    except ValueError:
        raise HTTPException(400, "Invalid tenant ID.")

    raw_body = await request.body()
    config   = (await db.execute(
        select(SmartOLTConfig).where(SmartOLTConfig.tenant_id == tenant_id)
    )).scalar_one_or_none()

    if not config:
        raise HTTPException(401, "SmartOLT not configured for this tenant.")

    if config.webhook_secret and x_signature:
        if not verify_smartolt_signature(config.webhook_secret, raw_body, x_signature):
            raise HTTPException(401, "Signature verification failed.")

    import json as _json
    try:
        payload = _json.loads(raw_body)
    except Exception:
        raise HTTPException(400, "Invalid JSON body.")

    tenant_id_ctx.set(tenant_id)
    result = await handle_smartolt_event(db, tenant_id, payload, config)
    await db.commit()

    if result is None:
        return {"success": True, "data": {"message": "Duplicate event — ignored."}}
    return {"success": True, "data": result}

def _out(o: OutageIncident) -> dict:
    return {
        "id":                   str(o.id),
        "reference":            o.reference,
        "title":                o.title,
        "description":          o.description,
        "severity":             o.severity,
        "status":               o.status,
        "olt_reference":        o.olt_reference,
        "source":               getattr(o, "source", "manual"),
        "affected_subscribers": getattr(o, "affected_subscribers", 0),
        "sla_deadline":         o.sla_deadline.isoformat() if getattr(o, "sla_deadline", None) else None,
        "breached_sla":         getattr(o, "breached_sla", False),
        "linked_task_id":       str(o.linked_task_id) if getattr(o, "linked_task_id", None) else None,
        "region_id":            str(o.region_id) if o.region_id else None,
        "resolved_at":          o.resolved_at.isoformat() if o.resolved_at else None,
        "created_at":           o.created_at.isoformat(),
    }


# ══════════════════════════════════════════════════════════════
#  ONBOARDING
# ══════════════════════════════════════════════════════════════

class StaffOnboardingRequest(Base):
    __tablename__      = "staff_onboarding_requests"
    __allow_unmapped__ = True
    id:                  Mapped[uuid.UUID]        = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:           Mapped[uuid.UUID]        = mapped_column(ForeignKey("tenants.id"), nullable=False)
    requested_by:        Mapped[uuid.UUID]        = mapped_column(ForeignKey("users.id"))
    proposed_first_name: Mapped[str]              = mapped_column(String(100), nullable=False)
    proposed_last_name:  Mapped[str]              = mapped_column(String(100), nullable=False)
    proposed_email:      Mapped[str]              = mapped_column(String(255), nullable=False)
    proposed_role_id:    Mapped[uuid.UUID]        = mapped_column(ForeignKey("roles.id"))
    department_id:       Mapped[uuid.UUID]        = mapped_column(ForeignKey("departments.id"))
    team_id:             Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id"))
    justification:            Mapped[str | None]               = mapped_column(Text)
    approval_status:          Mapped[str]                      = mapped_column(String(20), default="pending_manager")
    manager_approved_by:      Mapped[uuid.UUID | None]         = mapped_column(ForeignKey("users.id"))
    manager_approved_at:      Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    manager_rejection_reason: Mapped[str | None]               = mapped_column(Text)
    approved_by:              Mapped[uuid.UUID | None]         = mapped_column(ForeignKey("users.id"))
    approved_at:              Mapped[datetime.datetime | None]
    provisioned_user_id:      Mapped[uuid.UUID | None]         = mapped_column(ForeignKey("users.id"))
    created_at:               Mapped[datetime.datetime]        = mapped_column(default=datetime.datetime.utcnow)


class SubmitOnboardingRequest(BaseModel):
    proposed_first_name: str; proposed_last_name: str; proposed_email: str
    proposed_role_id: uuid.UUID; department_id: uuid.UUID
    team_id: Optional[uuid.UUID] = None; justification: Optional[str] = None


router_onboarding = APIRouter()

@router_onboarding.get("")
async def list_onboarding(status: Optional[str] = Query(None),
                           db: AsyncSession = Depends(get_db), _: User = Depends(check_permission("onboarding.manage"))):
    q = select(StaffOnboardingRequest).order_by(StaffOnboardingRequest.created_at.desc())
    if status: q = q.where(StaffOnboardingRequest.approval_status == status)
    rows = (await db.execute(q)).scalars().all()
    return {"success": True, "data": {"items": [_onb(r) for r in rows], "total": len(rows)}}

@router_onboarding.post("", status_code=201)
async def submit_onboarding(p: SubmitOnboardingRequest, db: AsyncSession = Depends(get_db),
                             caller: User = Depends(check_permission("onboarding.manage"))):
    r = StaffOnboardingRequest(
        tenant_id=caller.tenant_id,
        requested_by=caller.id, proposed_first_name=p.proposed_first_name,
        proposed_last_name=p.proposed_last_name, proposed_email=p.proposed_email,
        proposed_role_id=p.proposed_role_id, department_id=p.department_id,
        team_id=p.team_id, justification=p.justification,
        approval_status="pending_manager",
    )
    db.add(r); await db.flush()
    await db.commit()
    return {"success": True, "data": _onb(r)}

@router_onboarding.patch("/{rid}/manager-approve")
async def manager_approve_onboarding(rid: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db),
                                      caller: User = Depends(check_permission("onboarding.manage"))):
    role_level = caller.role.level if caller.role else 1
    if role_level < 4:
        raise HTTPException(403, "Manager approval requires role level 4 or above.")

    r = (await db.execute(select(StaffOnboardingRequest).where(
        StaffOnboardingRequest.id == rid))).scalar_one_or_none()
    if not r: raise HTTPException(404, "Request not found.")
    if r.approval_status != "pending_manager":
        raise HTTPException(400, "Request is not awaiting manager approval.")

    caller_dept = caller.staff_profile.department_id if caller.staff_profile else None
    if caller_dept != r.department_id:
        raise HTTPException(403, "You may only approve onboarding requests for your own department.")

    r.approval_status    = "pending_admin"
    r.manager_approved_by = caller.id
    r.manager_approved_at = datetime.datetime.utcnow()
    await db.flush()

    from app.events.bus import event_bus
    await event_bus.emit("onboarding.manager_approved", {
        "request_id":     str(r.id),
        "candidate_name": f"{r.proposed_first_name} {r.proposed_last_name}",
        "manager_id":     str(caller.id),
    })
    await db.commit()
    return {"success": True, "data": _onb(r)}


@router_onboarding.patch("/{rid}/approve")
async def approve_onboarding(rid: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db),
                              caller: User = Depends(check_permission("onboarding.manage"))):
    r = (await db.execute(select(StaffOnboardingRequest).where(
        StaffOnboardingRequest.id == rid))).scalar_one_or_none()
    if not r: raise HTTPException(404, "Request not found.")
    if r.approval_status == "pending_manager":
        raise HTTPException(400, "Manager approval required first.")
    if r.approval_status != "pending_admin":
        raise HTTPException(400, "Request is not awaiting admin approval.")

    # ── Auto-provision user + staff profile ──────────────────
    import secrets
    from app.core.security import hash_password, create_invite_token

    temp_password = secrets.token_urlsafe(24)
    username      = r.proposed_email.split("@")[0] + f"_{secrets.token_hex(3)}"

    new_user = User(
        tenant_id=caller.tenant_id,
        username=username,
        email=r.proposed_email,
        password_hash=hash_password(temp_password),
        role_id=r.proposed_role_id,
        is_active=False,
    )
    db.add(new_user)
    await db.flush()

    staff_code = f"OPS-{str(new_user.id)[:8].upper()}"
    profile = StaffProfile(
        tenant_id=caller.tenant_id,
        user_id=new_user.id,
        staff_code=staff_code,
        first_name=r.proposed_first_name,
        last_name=r.proposed_last_name,
        department_id=r.department_id,
        team_id=r.team_id,
        status="active",
        created_by=caller.id,
        joined_at=datetime.date.today(),
    )
    db.add(profile)

    r.approval_status    = "approved"
    r.approved_by        = caller.id
    r.approved_at        = datetime.datetime.utcnow()
    r.provisioned_user_id = new_user.id
    await db.flush()

    invite_token = create_invite_token(str(new_user.id))

    from app.core.config import settings
    from app.events.bus import event_bus
    await event_bus.emit("onboarding.approved", {
        "email":          r.proposed_email,
        "candidate_name": f"{r.proposed_first_name} {r.proposed_last_name}",
        "invite_token":   invite_token,
        "invite_url":     f"{settings.FRONTEND_URL}/activate?token={invite_token}",
        "user_id":        str(new_user.id),
    })
    await db.commit()
    return {"success": True, "data": _onb(r)}

class RejectOnboardingRequest(BaseModel):
    reason: Optional[str] = None


@router_onboarding.patch("/{rid}/reject")
async def reject_onboarding(rid: uuid.UUID = Path(...), body: RejectOnboardingRequest = RejectOnboardingRequest(),
                             db: AsyncSession = Depends(get_db),
                             caller: User = Depends(check_permission("onboarding.manage"))):
    r = (await db.execute(select(StaffOnboardingRequest).where(
        StaffOnboardingRequest.id == rid))).scalar_one_or_none()
    if not r: raise HTTPException(404, "Request not found.")
    if r.approval_status not in ("pending_manager", "pending_admin"):
        raise HTTPException(400, "Request cannot be rejected in its current state.")

    is_manager_phase = r.approval_status == "pending_manager"
    if is_manager_phase:
        role_level = caller.role.level if caller.role else 1
        if role_level < 4:
            raise HTTPException(403, "Manager phase rejection requires role level 4 or above.")
        caller_dept = caller.staff_profile.department_id if caller.staff_profile else None
        if caller_dept != r.department_id:
            raise HTTPException(403, "You may only reject onboarding requests for your own department.")
        r.manager_rejection_reason = body.reason

    r.approval_status = "rejected"
    r.approved_by     = caller.id
    r.approved_at     = datetime.datetime.utcnow()
    await db.flush()
    await db.commit()
    return {"success": True, "data": _onb(r)}

def _onb(r: StaffOnboardingRequest) -> dict:
    return {
        "id":                      str(r.id),
        "proposed_first_name":     r.proposed_first_name,
        "proposed_last_name":      r.proposed_last_name,
        "proposed_email":          r.proposed_email,
        "approval_status":         r.approval_status,
        "department_id":           str(r.department_id) if r.department_id else None,
        "team_id":                 str(r.team_id) if r.team_id else None,
        "justification":           r.justification,
        "manager_approved_by":     str(r.manager_approved_by) if r.manager_approved_by else None,
        "manager_approved_at":     r.manager_approved_at.isoformat() if r.manager_approved_at else None,
        "manager_rejection_reason": r.manager_rejection_reason,
        "approved_by":             str(r.approved_by) if r.approved_by else None,
        "approved_at":             r.approved_at.isoformat() if r.approved_at else None,
        "created_at":              r.created_at.isoformat(),
    }


# ══════════════════════════════════════════════════════════════
#  NOTIFICATIONS
# ══════════════════════════════════════════════════════════════

class Notification(Base):
    __tablename__      = "notifications"
    __allow_unmapped__ = True
    id:                    Mapped[uuid.UUID]          = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id:             Mapped[uuid.UUID]          = mapped_column(ForeignKey("tenants.id"), nullable=False)
    recipient_id:          Mapped[uuid.UUID]          = mapped_column(ForeignKey("users.id"), nullable=False)
    type:                  Mapped[str]                = mapped_column(String(50))
    title:                 Mapped[str]                = mapped_column(String(200), nullable=False)
    body:                  Mapped[str | None]         = mapped_column(Text)
    is_read:               Mapped[bool]               = mapped_column(Boolean, default=False)
    action_url:            Mapped[str | None]         = mapped_column(String(500))
    created_at:            Mapped[datetime.datetime]  = mapped_column(default=datetime.datetime.utcnow)
    # Phase 5 enhancements (migration 0047)
    notification_category: Mapped[str | None]         = mapped_column(String(30), default="general")
    related_task_id:       Mapped[uuid.UUID | None]   = mapped_column(ForeignKey("tasks.id"))
    related_project_id:    Mapped[uuid.UUID | None]   = mapped_column(ForeignKey("projects.id"))
    related_dept_id:       Mapped[uuid.UUID | None]   = mapped_column(ForeignKey("departments.id"))
    sender_id:             Mapped[uuid.UUID | None]   = mapped_column(ForeignKey("users.id"))


router_notifications = APIRouter()

@router_notifications.get("")
async def list_notifications(db: AsyncSession = Depends(get_db),
                              caller: User = Depends(get_current_user)):
    rows = (await db.execute(
        select(Notification).where(Notification.recipient_id == caller.id)
        .order_by(Notification.created_at.desc()).limit(50)
    )).scalars().all()
    return {"success": True, "data": [_notif(n) for n in rows]}

@router_notifications.get("/unread-count")
async def unread_count(db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    count = (await db.execute(
        select(func.count()).where(Notification.recipient_id == caller.id,
                                    Notification.is_read == False)
    )).scalar_one()
    return {"success": True, "data": {"count": count}}

@router_notifications.patch("/{nid}/read")
async def mark_read(nid: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db),
                     caller: User = Depends(get_current_user)):
    n = (await db.execute(select(Notification).where(
        Notification.id == nid, Notification.recipient_id == caller.id))).scalar_one_or_none()
    if n: n.is_read = True; await db.flush()
    return {"success": True}

@router_notifications.patch("/read-all")
async def mark_all_read(db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    from sqlalchemy import update
    await db.execute(update(Notification).where(
        Notification.recipient_id == caller.id, Notification.is_read == False
    ).values(is_read=True))
    return {"success": True}

def _notif(n: Notification) -> dict:
    return {
        "id":                    str(n.id),
        "type":                  n.type,
        "title":                 n.title,
        "body":                  n.body,
        "is_read":               n.is_read,
        "action_url":            n.action_url,
        "notification_category": getattr(n, "notification_category", "general"),
        "related_task_id":       str(n.related_task_id) if getattr(n, "related_task_id", None) else None,
        "related_project_id":    str(n.related_project_id) if getattr(n, "related_project_id", None) else None,
        "related_dept_id":       str(n.related_dept_id) if getattr(n, "related_dept_id", None) else None,
        "sender_id":             str(n.sender_id) if getattr(n, "sender_id", None) else None,
        "created_at":            n.created_at.isoformat(),
    }


# ══════════════════════════════════════════════════════════════
#  PROJECTS
# ══════════════════════════════════════════════════════════════
# Project model is imported from projects.models at the top of this file

class CreateProjectRequest(BaseModel):
    name: str
    project_type: str = "internal"
    owner_id: Optional[uuid.UUID] = None
    description: Optional[str] = None
    department_id: Optional[uuid.UUID] = None
    due_date: Optional[str] = None

    @field_validator("owner_id", "department_id", "due_date", mode="before")
    def _normalize_blank_strings(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


VALID_PROJECT_TYPES = {
    "internal", "external", "cable_upgrade", "olt_installation", "procurement",
    # Align with frontend UI labels:
    "infrastructure", "software", "operations", "security",
}
TEAM_LEAD_PROJECT_TYPES = {"internal", "cable_upgrade", "infrastructure", "operations"}


async def _generate_project_ticket_number(db: AsyncSession) -> str:
    """Generate next per-tenant PRJ-YYYY-NNNN identifier (RLS scopes to tenant)."""
    year   = datetime.datetime.utcnow().year
    prefix = f"PRJ-{year}-"
    max_seq = (await db.execute(
        select(func.max(cast(func.right(Project.ticket_number, 4), Integer)))
        .where(Project.ticket_number.like(f"{prefix}%"))
    )).scalar_one_or_none()
    return f"{prefix}{(max_seq or 0) + 1:04d}"


router_projects = APIRouter()

@router_projects.get("")
async def list_projects(status: Optional[str] = Query(None),
                         db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    q = select(Project).order_by(Project.created_at.desc())
    if status: q = q.where(Project.status == status)
    rows = (await db.execute(q)).scalars().all()
    return {"success": True, "data": {"items": [_proj(p) for p in rows], "total": len(rows)}}

@router_projects.post("", status_code=201)
async def create_project(p: CreateProjectRequest, db: AsyncSession = Depends(get_db),
                          caller: User = Depends(check_permission("leads.manage"))):
    if p.project_type not in VALID_PROJECT_TYPES:
        raise HTTPException(status_code=422,
            detail=f"Invalid project_type. Must be one of: {sorted(VALID_PROJECT_TYPES)}")

    # Permission already enforced by check_permission("leads.manage") — no extra role level gate.

    # Type-specific field requirements (soft — frontend provides defaults)
    if p.project_type == "internal" and not p.owner_id and not p.department_id:
        pass  # owner_id or department_id preferred but not enforced to avoid 422 on create

    department_id = p.department_id
    if p.owner_id:
        owner = (await db.execute(select(User).where(User.id == p.owner_id))).scalar_one_or_none()
        if owner and owner.staff_profile:
            department_id = owner.staff_profile.department_id

    ticket_number = await _generate_project_ticket_number(db)
    proj = Project(
        name=p.name,
        description=p.description,
        project_type=p.project_type,
        department_id=department_id,
        owner_id=p.owner_id,
        due_date=datetime.date.fromisoformat(p.due_date) if p.due_date else None,
        tenant_id=caller.tenant_id,
        ticket_number=ticket_number,
    )
    db.add(proj); await db.flush()
    await db.commit()
    return {"success": True, "data": _proj(proj)}


def _proj(p: Project) -> dict:
    return {"id": str(p.id), "name": p.name, "description": p.description,
            "status": p.status, "project_type": p.project_type,
            "ticket_number": p.ticket_number,
            "department_id": str(p.department_id) if p.department_id else None,
            "owner_id": str(p.owner_id) if p.owner_id else None,
            "completion_pct": p.completion_pct,
            "pipeline_status": p.pipeline_status,
            "current_stage_id": str(p.current_stage_id) if p.current_stage_id else None,
            "due_date": p.due_date.isoformat() if p.due_date else None,
            "created_at": p.created_at.isoformat()}


@router_projects.get("/{id}")
async def get_project(id: uuid.UUID, db: AsyncSession = Depends(get_db),
                       _: User = Depends(get_current_user)):
    proj = (await db.execute(select(Project).where(Project.id == id))).scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"success": True, "data": _proj(proj)}


@router_projects.get("/{id}/progress")
async def get_project_progress(id: uuid.UUID, db: AsyncSession = Depends(get_db),
                                _: User = Depends(get_current_user)):
    proj = (await db.execute(select(Project).where(Project.id == id))).scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found.")
    from app.modules.projects.models import ProjectPipelineStage
    stages = (await db.execute(
        select(ProjectPipelineStage).where(ProjectPipelineStage.project_id == id)
    )).scalars().all()
    total = len(stages)
    if total == 0:
        return {"success": True, "data": {"progress": proj.completion_pct, "total_stages": 0, "completed_stages": 0}}
    completed = sum(1 for s in stages if s.status == "approved")
    progress = round(completed / total * 100)
    return {"success": True, "data": {"progress": progress, "total_stages": total, "completed_stages": completed}}


# Pipeline endpoints
@router_projects.get("/{id}/pipeline")
async def get_project_pipeline(id: uuid.UUID, db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    pipeline = await get_pipeline(id, db, caller)
    return {"success": True, "data": pipeline}

@router_projects.post("/{id}/pipeline/start")
async def start_project_pipeline(id: uuid.UUID, body: dict, db: AsyncSession = Depends(get_db), caller: User = Depends(check_permission("pipeline.advance"))):
    if "workflow_id" in body and body["workflow_id"]:
        stage = await start_graph_pipeline(id, uuid.UUID(body["workflow_id"]), db, caller)
    else:
        stage = await start_pipeline(id, uuid.UUID(body["template_id"]), db, caller)
    return {"success": True, "data": {"stage_id": str(stage.id)}}

@router_projects.post("/{id}/pipeline/advance")
async def advance_project_stage(id: uuid.UUID, body: AdvanceStageRequest, db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    stage = await advance_stage(id, body.comment, db, caller)
    return {"success": True, "data": {"stage_id": str(stage.id)}}

@router_projects.post("/{id}/pipeline/pushback")
async def push_back_project_stage(id: uuid.UUID, body: PushBackRequest, db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    stage = await push_back_stage(id, body.reason, body.comment, db, caller)
    return {"success": True, "data": {"stage_id": str(stage.id)}}

@router_projects.post("/{id}/pipeline/stages/{stage_id}/comments")
async def add_project_stage_comment(id: uuid.UUID, stage_id: uuid.UUID, body: StageCommentCreate, db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    comment = await add_stage_comment(id, stage_id, body.body, body.comment_type, db, caller)
    return {"success": True, "data": {"comment_id": str(comment.id)}}

@router_projects.get("/{id}/pipeline/stages/{stage_id}/comments")
async def get_project_stage_comments(id: uuid.UUID, stage_id: uuid.UUID, db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    from app.modules.projects.models import ProjectStageComment
    comments = await db.execute(
        select(ProjectStageComment)
        .where(ProjectStageComment.stage_id == stage_id)
        .order_by(ProjectStageComment.created_at)
    )
    comments = comments.scalars().all()
    return {"success": True, "data": comments}


class ApproveStageRequest(BaseModel):
    notes: Optional[str] = None


@router_projects.post("/{id}/pipeline/stages/{stage_id}/approve")
async def approve_project_stage(
    id: uuid.UUID, stage_id: uuid.UUID,
    body: ApproveStageRequest = ApproveStageRequest(),
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(get_current_user),
):
    """Grant formal approval for a stage gate. Requires Team Lead+ or department match."""
    approval = await approve_stage(id, stage_id, body.notes, db, caller)
    await db.commit()
    return {
        "success":     True,
        "data": {
            "approval_id": str(approval.id),
            "stage_id":    str(approval.stage_id),
            "approver_id": str(approval.approver_id),
            "approved_at": approval.approved_at.isoformat() if approval.approved_at else None,
            "notes":       approval.notes,
        },
    }

@router_projects.get("/pipeline-templates")
async def get_pipeline_templates(db: AsyncSession = Depends(get_db), caller: User = Depends(get_current_user)):
    templates = await get_all_templates(db)
    return {"success": True, "data": templates}

@router_projects.post("/pipeline-templates")
async def create_pipeline_template(body: PipelineTemplateCreate, db: AsyncSession = Depends(get_db), caller: User = Depends(check_permission("settings.admin"))):
    template = await create_template(body, db, caller)
    return {"success": True, "data": template}


# ══════════════════════════════════════════════════════════════
#  REPORTS
# ══════════════════════════════════════════════════════════════

router_reports = APIRouter()

@router_reports.get("/summary")
async def get_summary(
    date_from: Optional[str] = Query(None, description="ISO date, e.g. 2026-01-01"),
    date_to:   Optional[str] = Query(None, description="ISO date, e.g. 2026-12-31"),
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("reports.view")),
):

    # Parse date window
    dt_from = datetime.datetime.fromisoformat(date_from) if date_from else None
    dt_to   = (datetime.datetime.fromisoformat(date_to) + datetime.timedelta(days=1)) if date_to else None

    # ── Staff metrics ──
    total_staff  = (await db.execute(select(func.count()).select_from(User).where(
        User.tenant_id == caller.tenant_id))).scalar_one()
    active_staff = (await db.execute(
        select(func.count()).select_from(SP)
        .join(User, User.id == SP.user_id)
        .where(User.tenant_id == caller.tenant_id, SP.status == "active")
    )).scalar_one()

    added_q = select(func.count()).select_from(SP).join(User, User.id == SP.user_id).where(
        User.tenant_id == caller.tenant_id)
    if dt_from: added_q = added_q.where(SP.created_at >= dt_from)
    if dt_to:   added_q = added_q.where(SP.created_at < dt_to)
    staff_added = (await db.execute(added_q)).scalar_one()

    # ── Outage metrics ──
    outage_q = select(OutageIncident).where(
        OutageIncident.tenant_id == caller.tenant_id,
        OutageIncident.status == "resolved",
    )
    if dt_from: outage_q = outage_q.where(OutageIncident.created_at >= dt_from)
    if dt_to:   outage_q = outage_q.where(OutageIncident.created_at < dt_to)
    resolved_outages = (await db.execute(outage_q)).scalars().all()

    mttr_hours = None
    if resolved_outages:
        total_mins = sum(
            (inc.resolved_at - inc.created_at).total_seconds() / 3600
            for inc in resolved_outages
            if inc.resolved_at and inc.created_at
        )
        counted = sum(1 for inc in resolved_outages if inc.resolved_at and inc.created_at)
        if counted > 0:
            mttr_hours = round(total_mins / counted, 2)

    # ── Task metrics ──
    task_q = select(func.count()).select_from(Task).where(Task.status == "done")
    total_task_q = select(func.count()).select_from(Task)
    tasks_done  = (await db.execute(task_q)).scalar_one()
    tasks_total = (await db.execute(total_task_q)).scalar_one()
    task_rate   = round(tasks_done / tasks_total, 4) if tasks_total else 0.0

    # ── Infrastructure metrics ──
    from app.modules.infrastructure.models import InfrastructureSite, InfrastructureNode
    infra_sites = (await db.execute(select(func.count()).select_from(InfrastructureSite).where(
        InfrastructureSite.tenant_id == caller.tenant_id,
        InfrastructureSite.status == "active",
    ))).scalar_one()
    infra_nodes = (await db.execute(select(func.count()).select_from(InfrastructureNode).where(
        InfrastructureNode.tenant_id == caller.tenant_id,
        InfrastructureNode.status == "active",
    ))).scalar_one()

    return {"success": True, "data": {
        "period": {"from": date_from, "to": date_to},
        "staff_total":           total_staff,
        "staff_active":          active_staff,
        "staff_added":           staff_added,
        "outages_resolved":      len(resolved_outages),
        "avg_mttr_hours":        mttr_hours,
        "tasks_completed":       tasks_done,
        "task_completion_rate":  task_rate,
        "active_sites":          infra_sites,
        "active_network_nodes":  infra_nodes,
    }}


@router_reports.get("/export/csv")
async def export_csv(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("reports.view")),
):
    q = select(SP).join(User, User.id == SP.user_id).where(
        User.tenant_id == caller.tenant_id
    )
    if date_from:
        q = q.where(SP.created_at >= datetime.datetime.fromisoformat(date_from))
    if date_to:
        q = q.where(SP.created_at < datetime.datetime.fromisoformat(date_to) + datetime.timedelta(days=1))
    rows = (await db.execute(q.limit(1000))).scalars().all()
    buf  = io.StringIO()
    w    = csv.writer(buf)
    w.writerow(["staff_code","first_name","last_name","status","employment_type","department","joined_at"])
    for r in rows:
        dept_name = r.department.name if r.department else ""
        w.writerow([r.staff_code, r.first_name, r.last_name, r.status,
                     r.employment_type, dept_name, str(r.joined_at or "")])
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv",
                              headers={"Content-Disposition": "attachment; filename=opsyn-report.csv"})


@router_reports.get("/outages/mttr")
async def get_outage_mttr(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    severity:  Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("reports.view")),
):
    """Mean Time to Resolution breakdown by severity."""
    q = select(OutageIncident).where(
        OutageIncident.tenant_id == caller.tenant_id,
        OutageIncident.status == "resolved",
        OutageIncident.resolved_at.isnot(None),
    )
    if date_from: q = q.where(OutageIncident.created_at >= datetime.datetime.fromisoformat(date_from))
    if date_to:   q = q.where(OutageIncident.created_at < datetime.datetime.fromisoformat(date_to) + datetime.timedelta(days=1))
    if severity:  q = q.where(OutageIncident.severity == severity)

    incidents = (await db.execute(q)).scalars().all()

    by_severity: dict[str, list[float]] = {}
    for inc in incidents:
        hrs = (inc.resolved_at - inc.created_at).total_seconds() / 3600
        by_severity.setdefault(inc.severity, []).append(hrs)

    breakdown = {
        sev: {
            "count": len(times),
            "avg_hours": round(sum(times) / len(times), 2),
            "max_hours": round(max(times), 2),
        }
        for sev, times in by_severity.items()
    }
    total = [h for times in by_severity.values() for h in times]
    return {"success": True, "data": {
        "overall_mttr_hours": round(sum(total) / len(total), 2) if total else None,
        "total_resolved": len(incidents),
        "by_severity": breakdown,
    }}


@router_reports.get("/staff/breakdown")
async def get_staff_breakdown(
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("reports.view")),
):
    """Headcount breakdown by department, region, employment type, and status."""
    from app.modules.organisation.models import Department, Region

    dept_rows = (await db.execute(
        select(Department.name, func.count(SP.id))
        .join(SP, SP.department_id == Department.id)
        .join(User, User.id == SP.user_id)
        .where(User.tenant_id == caller.tenant_id)
        .group_by(Department.name)
        .order_by(func.count(SP.id).desc())
    )).fetchall()

    region_rows = (await db.execute(
        select(Region.name, func.count(SP.id))
        .join(SP, SP.region_id == Region.id)
        .join(User, User.id == SP.user_id)
        .where(User.tenant_id == caller.tenant_id)
        .group_by(Region.name)
        .order_by(func.count(SP.id).desc())
    )).fetchall()

    emp_rows = (await db.execute(
        select(SP.employment_type, func.count(SP.id))
        .join(User, User.id == SP.user_id)
        .where(User.tenant_id == caller.tenant_id)
        .group_by(SP.employment_type)
        .order_by(func.count(SP.id).desc())
    )).fetchall()

    status_rows = (await db.execute(
        select(SP.status, func.count(SP.id))
        .join(User, User.id == SP.user_id)
        .where(User.tenant_id == caller.tenant_id)
        .group_by(SP.status)
        .order_by(func.count(SP.id).desc())
    )).fetchall()

    total = sum(r[1] for r in status_rows)

    return {"success": True, "data": {
        "total":              total,
        "by_department":      [{"name": r[0] or "Unassigned", "count": r[1]} for r in dept_rows],
        "by_region":          [{"name": r[0] or "Unassigned", "count": r[1]} for r in region_rows],
        "by_employment_type": [{"type": r[0] or "unknown",    "count": r[1]} for r in emp_rows],
        "by_status":          [{"status": r[0] or "unknown",  "count": r[1]} for r in status_rows],
    }}


@router_reports.get("/tasks/breakdown")
async def get_tasks_breakdown(
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("reports.view")),
):
    """Task count breakdown by status and department."""
    from app.modules.organisation.models import Department

    status_rows = (await db.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.tenant_id == caller.tenant_id)
        .group_by(Task.status)
        .order_by(func.count(Task.id).desc())
    )).fetchall()

    overdue = (await db.execute(
        select(func.count()).select_from(Task).where(
            Task.tenant_id == caller.tenant_id,
            Task.deadline < datetime.datetime.utcnow(),
            Task.status.notin_(["done", "archived"]),
        )
    )).scalar_one()

    dept_rows = (await db.execute(
        select(Department.name, func.count(Task.id))
        .join(SP, SP.user_id == Task.assignee_user_id)
        .join(Department, Department.id == SP.department_id)
        .where(Task.tenant_id == caller.tenant_id, Task.assignee_user_id.isnot(None))
        .group_by(Department.name)
        .order_by(func.count(Task.id).desc())
        .limit(10)
    )).fetchall()

    total = (await db.execute(
        select(func.count()).select_from(Task).where(Task.tenant_id == caller.tenant_id)
    )).scalar_one()

    return {"success": True, "data": {
        "total":          total,
        "overdue":        overdue,
        "by_status":      [{"status": r[0], "count": r[1]} for r in status_rows],
        "by_department":  [{"name": r[0],   "count": r[1]} for r in dept_rows],
    }}


@router_reports.get("/projects/breakdown")
async def get_projects_breakdown(
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(check_permission("reports.view")),
):
    """Project count breakdown by type, pipeline status, and status."""
    from app.modules.projects.models import Project

    type_rows = (await db.execute(
        select(Project.project_type, func.count(Project.id))
        .where(Project.tenant_id == caller.tenant_id)
        .group_by(Project.project_type)
        .order_by(func.count(Project.id).desc())
    )).fetchall()

    pipe_rows = (await db.execute(
        select(Project.pipeline_status, func.count(Project.id))
        .where(Project.tenant_id == caller.tenant_id)
        .group_by(Project.pipeline_status)
        .order_by(func.count(Project.id).desc())
    )).fetchall()

    status_rows = (await db.execute(
        select(Project.status, func.count(Project.id))
        .where(Project.tenant_id == caller.tenant_id)
        .group_by(Project.status)
        .order_by(func.count(Project.id).desc())
    )).fetchall()

    total = (await db.execute(
        select(func.count()).select_from(Project).where(Project.tenant_id == caller.tenant_id)
    )).scalar_one()

    return {"success": True, "data": {
        "total":              total,
        "by_type":            [{"type":   r[0] or "unknown", "count": r[1]} for r in type_rows],
        "by_pipeline_status": [{"status": r[0] or "unknown", "count": r[1]} for r in pipe_rows],
        "by_status":          [{"status": r[0] or "unknown", "count": r[1]} for r in status_rows],
    }}


@router_reports.get("/intel-strip")
async def get_intel_strip(
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(get_current_user),
):
    """Five KPI chips for the IntelStrip bar. Redis-cached for 30 seconds per tenant."""
    import json
    from app.core.redis_client import redis_pool

    cache_key = f"intel_strip:{caller.tenant_id}"
    if redis_pool.client:
        cached = await redis_pool.client.get(cache_key)
        if cached:
            return {"success": True, "data": json.loads(cached)}

    today_start = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end   = today_start + datetime.timedelta(days=1)

    # 1. Active outages
    active_outages = (await db.execute(
        select(func.count()).select_from(OutageIncident).where(
            OutageIncident.tenant_id == caller.tenant_id,
            OutageIncident.status.in_(["active", "monitoring"]),
        )
    )).scalar_one()

    # 2. Overdue tasks (deadline < now, not done/archived)
    tasks_overdue = (await db.execute(
        select(func.count()).select_from(Task).where(
            Task.tenant_id == caller.tenant_id,
            Task.deadline < datetime.datetime.utcnow(),
            Task.status.notin_(["done", "archived"]),
        )
    )).scalar_one()

    # 3. Staff on-call today (stub: active staff count — replace with on_call model when available)
    staff_on_call = (await db.execute(
        select(func.count()).select_from(SP)
        .where(SP.tenant_id == caller.tenant_id, SP.status == "active")
    )).scalar_one()

    # 4. Avg MTTR today (minutes)
    resolved_today = (await db.execute(
        select(OutageIncident).where(
            OutageIncident.tenant_id == caller.tenant_id,
            OutageIncident.status == "resolved",
            OutageIncident.resolved_at >= today_start,
            OutageIncident.resolved_at < today_end,
            OutageIncident.resolved_at.isnot(None),
        )
    )).scalars().all()
    avg_mttr_mins: float | None = None
    if resolved_today:
        total_mins = sum(
            (inc.resolved_at - inc.created_at).total_seconds() / 60
            for inc in resolved_today
            if inc.resolved_at and inc.created_at
        )
        avg_mttr_mins = round(total_mins / len(resolved_today), 1)

    # 5. Pending onboarding
    pending_onboarding = (await db.execute(
        select(func.count()).select_from(StaffOnboardingRequest).where(
            StaffOnboardingRequest.tenant_id == caller.tenant_id,
            StaffOnboardingRequest.approval_status.in_(["pending_manager", "pending_admin"]),
        )
    )).scalar_one()

    result = {
        "active_outages":     active_outages,
        "tasks_overdue":      tasks_overdue,
        "staff_on_call":      staff_on_call,
        "avg_mttr_mins":      avg_mttr_mins,
        "pending_onboarding": pending_onboarding,
    }

    if redis_pool.client:
        await redis_pool.client.setex(cache_key, 30, json.dumps(result))

    return {"success": True, "data": result}


@router_reports.get("/infrastructure")
async def get_infrastructure_report(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("reports.view")),
):
    """Capacity utilisation by site, unresolved alert counts, and port-level summary."""
    result = (await db.execute(
        text("""
            SELECT
                s.id, s.name, s.site_type, s.status,
                COALESCE(SUM(p.used_capacity),  0) AS used,
                COALESCE(SUM(p.total_capacity), 0) AS total,
                COUNT(DISTINCT n.id)                AS node_count,
                COUNT(DISTINCT p.id)                AS port_count
            FROM infrastructure_sites s
            LEFT JOIN infrastructure_nodes n ON n.site_id = s.id  AND n.tenant_id = :tid
            LEFT JOIN infra_ports          p ON p.node_id  = n.id AND p.tenant_id = :tid
            WHERE s.tenant_id = :tid
            GROUP BY s.id, s.name, s.site_type, s.status
            ORDER BY used DESC
        """),
        {"tid": str(caller.tenant_id)},
    )).fetchall()

    alert_rows = (await db.execute(
        text("""
            SELECT severity, COUNT(*) AS cnt
            FROM infra_capacity_alerts
            WHERE tenant_id = :tid AND is_resolved = false
            GROUP BY severity
        """),
        {"tid": str(caller.tenant_id)},
    )).fetchall()

    recent_alerts = (await db.execute(
        text("""
            SELECT a.id, a.severity, a.alert_type, a.current_pct, a.threshold_pct,
                   a.message, a.created_at,
                   s.name AS site_name, n.name AS node_name
            FROM infra_capacity_alerts a
            LEFT JOIN infrastructure_sites s ON s.id = a.site_id
            LEFT JOIN infrastructure_nodes n ON n.id = a.node_id
            WHERE a.tenant_id = :tid AND a.is_resolved = false
            ORDER BY a.created_at DESC
            LIMIT 20
        """),
        {"tid": str(caller.tenant_id)},
    )).fetchall()

    return {
        "success": True,
        "data": {
            "sites": [
                {
                    "id": str(r[0]), "name": r[1], "site_type": r[2], "status": r[3],
                    "used": int(r[4]), "total": int(r[5]),
                    "utilisation_pct": round(int(r[4]) / max(int(r[5]), 1) * 100),
                    "node_count": int(r[6]), "port_count": int(r[7]),
                }
                for r in result
            ],
            "alert_summary": {row[0]: int(row[1]) for row in alert_rows},
            "recent_alerts": [
                {
                    "id": str(a[0]), "severity": a[1], "alert_type": a[2],
                    "current_pct": a[3], "threshold_pct": a[4], "message": a[5],
                    "created_at": a[6].isoformat() if a[6] else None,
                    "site_name": a[7], "node_name": a[8],
                }
                for a in recent_alerts
            ],
        },
    }


@router_reports.get("/shifts")
async def get_shifts_report(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("reports.view")),
):
    """Shift coverage, oncall load per staff, and swap request stats."""

    coverage = (await db.execute(
        text("""
            SELECT
                sa.shift_id,
                sh.name AS shift_name, sh.shift_type,
                COUNT(sa.id)  AS assignments,
                sh.start_time, sh.end_time
            FROM shift_assignments sa
            JOIN shifts sh ON sh.id = sa.shift_id
            WHERE sh.tenant_id = :tid
              AND sa.status = 'confirmed'
              AND sa.date >= (CURRENT_DATE - INTERVAL '30 days')
            GROUP BY sa.shift_id, sh.name, sh.shift_type, sh.start_time, sh.end_time
            ORDER BY assignments DESC
            LIMIT 20
        """),
        {"tid": str(caller.tenant_id)},
    )).fetchall()

    oncall_load = (await db.execute(
        text("""
            SELECT
                sp.first_name || ' ' || sp.last_name AS staff_name,
                COUNT(sa.id) AS oncall_shifts
            FROM shift_assignments sa
            JOIN shifts sh ON sh.id = sa.shift_id AND sh.shift_type = 'oncall'
            JOIN users u ON u.id = sa.user_id
            JOIN staff_profiles sp ON sp.user_id = u.id
            WHERE sh.tenant_id = :tid
              AND sa.status = 'confirmed'
              AND sa.date >= (CURRENT_DATE - INTERVAL '30 days')
            GROUP BY sp.first_name, sp.last_name
            ORDER BY oncall_shifts DESC
            LIMIT 10
        """),
        {"tid": str(caller.tenant_id)},
    )).fetchall()

    swap_stats = (await db.execute(
        text("""
            SELECT status, COUNT(*) AS cnt
            FROM shift_swap_requests
            WHERE tenant_id = :tid
              AND created_at >= NOW() - INTERVAL '30 days'
            GROUP BY status
        """),
        {"tid": str(caller.tenant_id)},
    )).fetchall()

    return {
        "success": True,
        "data": {
            "coverage": [
                {
                    "shift_name": r[1], "shift_type": r[2],
                    "assignments": int(r[3]),
                    "start_time": str(r[4]) if r[4] else None,
                    "end_time":   str(r[5]) if r[5] else None,
                }
                for r in coverage
            ],
            "oncall_load": [
                {"staff_name": r[0], "oncall_shifts": int(r[1])}
                for r in oncall_load
            ],
            "swap_requests": {row[0]: int(row[1]) for row in swap_stats},
        },
    }


@router_reports.get("/sla")
async def get_sla_report(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("reports.view")),
):
    """SLA breach rate by severity, avg time-to-breach, worst-performing OLTs."""
    by_severity = (await db.execute(
        text("""
            SELECT
                severity,
                COUNT(*)                                        AS total,
                COUNT(*) FILTER (WHERE breached_sla = true)    AS breached,
                AVG(EXTRACT(EPOCH FROM (sla_deadline - created_at)) / 60.0)
                    FILTER (WHERE breached_sla = true)          AS avg_mins_to_breach
            FROM outage_incidents
            WHERE tenant_id = :tid
              AND sla_deadline IS NOT NULL
              AND created_at >= NOW() - INTERVAL '90 days'
            GROUP BY severity
            ORDER BY breached DESC
        """),
        {"tid": str(caller.tenant_id)},
    )).fetchall()

    worst_olts = (await db.execute(
        text("""
            SELECT
                olt_reference,
                COUNT(*) AS total_outages,
                COUNT(*) FILTER (WHERE breached_sla = true) AS breached,
                AVG(EXTRACT(EPOCH FROM (COALESCE(resolved_at, NOW()) - created_at)) / 3600.0)
                    AS avg_mttr_hours
            FROM outage_incidents
            WHERE tenant_id = :tid
              AND created_at >= NOW() - INTERVAL '90 days'
              AND olt_reference IS NOT NULL
            GROUP BY olt_reference
            ORDER BY breached DESC
            LIMIT 10
        """),
        {"tid": str(caller.tenant_id)},
    )).fetchall()

    return {
        "success": True,
        "data": {
            "by_severity": [
                {
                    "severity": r[0],
                    "total": int(r[1]), "breached": int(r[2]),
                    "breach_rate_pct": round(int(r[2]) / max(int(r[1]), 1) * 100),
                    "avg_mins_to_breach": round(float(r[3]), 1) if r[3] else None,
                }
                for r in by_severity
            ],
            "worst_olts": [
                {
                    "olt_reference": r[0],
                    "total_outages": int(r[1]), "breached": int(r[2]),
                    "breach_rate_pct": round(int(r[2]) / max(int(r[1]), 1) * 100),
                    "avg_mttr_hours": round(float(r[3]), 1) if r[3] else None,
                }
                for r in worst_olts
            ],
        },
    }


# ══════════════════════════════════════════════════════════════
#  PERMISSIONS (stub — real enforcement is in dependencies/auth.py)
# ══════════════════════════════════════════════════════════════

router_permissions = APIRouter()

@router_permissions.get("/permissions")
async def list_permissions(_: User = Depends(check_permission("settings.admin"))):
    return {"success": True, "data": [
        {"key": "staff.create",        "description": "Create staff accounts"},
        {"key": "staff.update",        "description": "Update staff profiles"},
        {"key": "staff.deactivate",    "description": "Deactivate staff accounts"},
        {"key": "roles.assign",        "description": "Assign roles to users"},
        {"key": "onboarding.approve",  "description": "Approve onboarding requests"},
        {"key": "onboarding.submit",   "description": "Submit onboarding requests"},
        {"key": "outage.manage",       "description": "Log and manage outage incidents"},
        {"key": "mec.review",          "description": "Perform MEC equipment reviews"},
        {"key": "audit.view",          "description": "View audit logs"},
        {"key": "tasks.manage",        "description": "Create and manage tasks"},
        {"key": "reports.view",        "description": "View operational reports"},
        {"key": "org.manage",          "description": "Manage departments, teams, regions"},
    ]}
