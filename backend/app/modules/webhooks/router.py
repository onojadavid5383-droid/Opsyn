# ============================================================
# OPSYN WEBHOOK RECEIVER — app/modules/webhooks/router.py
# Sprint 3 — S3.3
#
# Public endpoint (HMAC-SHA256, no JWT):
#   POST /webhooks/receive
#   Headers: X-Webhook-App, X-Webhook-Tenant, X-Webhook-Signature
#
# Admin key management (JWT + settings.admin):
#   GET    /webhooks/keys
#   POST   /webhooks/keys
#   DELETE /webhooks/keys/{key_id}
#
# Supported apps: hr, finance, sales, field_tech, coverage
# ============================================================

from __future__ import annotations

import datetime
import hashlib
import hmac as hmac_lib
import json
import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.permissions import check_permission
from app.modules.staff.models import User
from app.modules.webhooks.models import WebhookApiKey

router = APIRouter()

VALID_APP_NAMES = {"hr", "finance", "sales", "field_tech", "coverage", "inventory", "integration"}


# ── Signature verification ────────────────────────────────────

def _verify_signature(secret: str, raw_body: bytes, signature: str) -> bool:
    expected = "sha256=" + hmac_lib.new(
        secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac_lib.compare_digest(expected, signature)


async def _get_active_key(
    db: AsyncSession, tenant_id: uuid.UUID, app_name: str
) -> WebhookApiKey:
    key = (await db.execute(
        select(WebhookApiKey).where(
            WebhookApiKey.tenant_id == tenant_id,
            WebhookApiKey.app_name  == app_name,
            WebhookApiKey.is_active.is_(True),
        )
    )).scalar_one_or_none()
    if not key:
        raise HTTPException(401, "No active webhook key for this app.")
    return key


# ── Shared task-creation helper ───────────────────────────────

async def _create_task_from_webhook(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    key: WebhookApiKey,
    *,
    title: str,
    description: str,
    source_app: str,
    priority: str = "medium",
    deadline_str: str | None = None,
    deadline_days: int = 30,
    department_id: uuid.UUID | None = None,
    tags: list | None = None,
) -> dict:
    import types as _types
    from app.modules.tasks.service import task_workflow_service
    from app.modules.staff.models import User as _User

    if not key.created_by:
        raise HTTPException(
            422,
            "Cannot create task: webhook key has no associated user. "
            "Re-create the key while logged in as an active staff member.",
        )
    caller = (await db.execute(
        select(_User).where(_User.id == key.created_by, _User.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not caller:
        raise HTTPException(422, "Webhook key owner not found in this tenant.")

    if not deadline_str:
        deadline_str = (
            datetime.datetime.utcnow() + datetime.timedelta(days=deadline_days)
        ).strftime("%Y-%m-%d")

    payload = _types.SimpleNamespace(
        title=title,
        description=description,
        deadline=deadline_str,
        priority=priority,
        department_id=department_id,
        assignee_user_id=None,
        tags=tags or [],
        estimated_hours=None,
        source_app=source_app,
        archive_refs=[],
        project_id=None,
    )
    task, project = await task_workflow_service.create_external_task(
        db, payload, caller, source_app=source_app,
    )
    return {
        "task_id":               str(task.id),
        "task_ticket":           task.ticket_number,
        "project_id":            str(project.id),
        "project_ticket_number": project.ticket_number,
    }


# ── Admin: key management ─────────────────────────────────────

class CreateKeyRequest(BaseModel):
    app_name: str


@router.get("/webhooks/keys")
async def list_keys(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("settings.admin")),
):
    keys = (await db.execute(
        select(WebhookApiKey)
        .where(WebhookApiKey.tenant_id == caller.tenant_id)
        .order_by(WebhookApiKey.created_at.desc())
    )).scalars().all()
    return {"success": True, "data": [
        {
            "id":         str(k.id),
            "app_name":   k.app_name,
            "is_active":  k.is_active,
            "created_at": k.created_at.isoformat(),
        }
        for k in keys
    ]}


@router.post("/webhooks/keys", status_code=201)
async def create_key(
    payload: CreateKeyRequest,
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    if payload.app_name not in VALID_APP_NAMES:
        raise HTTPException(
            400, f"app_name must be one of: {', '.join(sorted(VALID_APP_NAMES))}"
        )

    raw_secret = secrets.token_hex(32)
    key = WebhookApiKey(
        tenant_id=caller.tenant_id,
        app_name=payload.app_name,
        secret_key=raw_secret,
        created_by=caller.id,
    )
    db.add(key)
    await db.flush()
    await db.commit()
    return {"success": True, "data": {
        "id":         str(key.id),
        "app_name":   key.app_name,
        "secret_key": raw_secret,
        "note":       "Store this secret immediately — it will not be shown again.",
        "created_at": key.created_at.isoformat(),
    }}


@router.delete("/webhooks/keys/{key_id}", status_code=204)
async def deactivate_key(
    key_id:  uuid.UUID    = Path(...),
    db:      AsyncSession = Depends(get_db),
    caller:  User         = Depends(check_permission("settings.admin")),
):
    key = (await db.execute(
        select(WebhookApiKey).where(
            WebhookApiKey.id        == key_id,
            WebhookApiKey.tenant_id == caller.tenant_id,
        )
    )).scalar_one_or_none()
    if not key:
        raise HTTPException(404, "Key not found.")
    key.is_active = False
    await db.flush()
    await db.commit()


# ── Receiver ──────────────────────────────────────────────────

@router.post("/webhooks/receive")
async def receive_webhook(
    request:               Request,
    x_webhook_app:       str = Header(..., alias="X-Webhook-App"),
    x_webhook_tenant:    str = Header(..., alias="X-Webhook-Tenant"),
    x_webhook_signature: str = Header(..., alias="X-Webhook-Signature"),
    db: AsyncSession = Depends(get_db),
):
    try:
        tenant_id = uuid.UUID(x_webhook_tenant)
    except ValueError:
        raise HTTPException(400, "Invalid X-Webhook-Tenant header — must be a UUID.")

    if x_webhook_app not in VALID_APP_NAMES:
        raise HTTPException(400, f"Unknown app '{x_webhook_app}'.")

    raw_body = await request.body()

    key = await _get_active_key(db, tenant_id, x_webhook_app)
    if not _verify_signature(key.secret_key, raw_body, x_webhook_signature):
        raise HTTPException(401, "Signature verification failed.")

    try:
        event_data = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON body.")

    event_type: str       = event_data.get("event", "")
    data:       dict      = event_data.get("data", {})

    _handlers = {
        "hr":          _handle_hr,
        "finance":     _handle_finance,
        "sales":       _handle_sales,
        "field_tech":  _handle_field_tech,
        "coverage":    _handle_coverage,
        "inventory":   _handle_inventory,
        "integration": _handle_integration,
    }
    result = await _handlers[x_webhook_app](db, tenant_id, key, event_type, data)
    return {"success": True, "event": event_type, "data": result}


# ── HR handler ────────────────────────────────────────────────

async def _handle_hr(
    db: AsyncSession, tenant_id: uuid.UUID, key: WebhookApiKey,
    event_type: str, data: dict[str, Any],
) -> dict:
    from app.modules.staff.models import StaffProfile
    from sqlalchemy.orm import selectinload

    if event_type == "staff.hired":
        email = data.get("email")
        if not email:
            raise HTTPException(422, "data.email required for staff.hired")

        existing = (await db.execute(
            select(User).where(User.email == email, User.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if existing:
            return {"message": "User already exists.", "user_id": str(existing.id)}

        from app.core.security import hash_password
        username = email.split("@")[0] + "_" + secrets.token_hex(3)
        user = User(
            tenant_id=tenant_id,
            username=username,
            email=email,
            password_hash=hash_password(secrets.token_hex(16)),
            is_active=False,
        )
        db.add(user)
        await db.flush()

        profile = StaffProfile(
            tenant_id=tenant_id,
            user_id=user.id,
            staff_code=f"WHK-{secrets.token_hex(3).upper()}",
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            job_title=data.get("job_title"),
            status="pending",
            created_by=key.created_by,
        )
        db.add(profile)
        await db.flush()
        hire_name = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip() or "New hire"
        task_info = await _create_task_from_webhook(
            db, tenant_id, key,
            title=f"Onboard new hire: {hire_name}",
            description=f"New hire onboarding. Position: {data.get('job_title', 'N/A')}. Email: {email}.",
            source_app="hr",
            priority="medium",
            deadline_days=14,
        )
        await db.commit()
        return {"message": "User created (pending onboarding).", "user_id": str(user.id), **task_info}

    elif event_type == "staff.terminated":
        email = data.get("email")
        if not email:
            raise HTTPException(422, "data.email required for staff.terminated")

        user = (await db.execute(
            select(User).where(User.email == email, User.tenant_id == tenant_id)
            .options(selectinload(User.staff_profile))
        )).scalar_one_or_none()
        if not user:
            raise HTTPException(404, f"No staff with email {email!r}.")

        user.is_active = False
        if user.staff_profile:
            user.staff_profile.status = "terminated"
            if data.get("effective_date"):
                try:
                    user.staff_profile.end_date = datetime.date.fromisoformat(
                        data["effective_date"]
                    )
                except ValueError:
                    pass

        await db.flush()
        await db.commit()
        return {"message": "Staff terminated.", "user_id": str(user.id)}

    elif event_type == "staff.transferred":
        email       = data.get("email")
        new_dept_id = data.get("new_department_id")
        if not email or not new_dept_id:
            raise HTTPException(422, "data.email and data.new_department_id required.")

        try:
            dept_uuid = uuid.UUID(new_dept_id)
        except ValueError:
            raise HTTPException(422, "data.new_department_id must be a valid UUID.")

        user = (await db.execute(
            select(User).where(User.email == email, User.tenant_id == tenant_id)
            .options(selectinload(User.staff_profile))
        )).scalar_one_or_none()
        if not user or not user.staff_profile:
            raise HTTPException(404, f"Staff with email {email!r} not found.")

        user.staff_profile.department_id = dept_uuid
        await db.flush()
        await db.commit()
        return {"message": "Staff transferred.", "user_id": str(user.id)}

    else:
        raise HTTPException(422, f"Unknown HR event: {event_type!r}")


# ── Finance handler ───────────────────────────────────────────

async def _handle_finance(
    db: AsyncSession, tenant_id: uuid.UUID, key: WebhookApiKey,
    event_type: str, data: dict[str, Any],
) -> dict:
    from app.modules.projects.models import Project
    from app.modules.activity.service import timeline_writer
    from app.core.context import tenant_id_ctx

    ticket = data.get("ticket_number")
    if not ticket:
        raise HTTPException(422, "data.ticket_number required.")

    project = (await db.execute(
        select(Project).where(
            Project.ticket_number == ticket,
            Project.tenant_id     == tenant_id,
        )
    )).scalar_one_or_none()
    if not project:
        raise HTTPException(404, f"Project {ticket!r} not found.")

    if event_type == "project.budget_approved":
        approver = data.get("approver", "Finance system")
        body = f"Budget approved by Finance ({approver})."
        if data.get("approved_amount"):
            body += f" Approved amount: {data['approved_amount']:,}."
    elif event_type == "project.budget_rejected":
        reason = data.get("reason", "No reason provided.")
        body = f"Budget rejected by Finance. Reason: {reason}"
    else:
        raise HTTPException(422, f"Unknown Finance event: {event_type!r}")

    ctx_token = tenant_id_ctx.set(tenant_id)
    try:
        await timeline_writer.write_system_event(
            db, entity_type="project", entity_id=project.id,
            body=body,
            meta={"source": "finance_webhook", "event": event_type, **data},
        )
    finally:
        tenant_id_ctx.reset(ctx_token)

    await db.commit()
    return {"message": "Finance event logged.", "project_id": str(project.id)}


# ── Sales handler ─────────────────────────────────────────────

async def _handle_sales(
    db: AsyncSession, tenant_id: uuid.UUID, key: WebhookApiKey,
    event_type: str, data: dict[str, Any],
) -> dict:
    if event_type not in ("lead.won", "lead.created"):
        raise HTTPException(422, f"Unknown Sales event: {event_type!r}")

    task_title = data.get("project_name") or data.get("client_name")
    if not task_title:
        raise HTTPException(422, "data.project_name or data.client_name required.")

    dept_id: uuid.UUID | None = None
    if data.get("department_id"):
        try:
            dept_id = uuid.UUID(data["department_id"])
        except ValueError:
            pass

    notes_parts = [f"Lead: {data.get('lead_id', 'N/A')}"]
    if data.get("estimated_value"):
        notes_parts.append(f"Est. value: {data['estimated_value']:,}")
    if data.get("notes"):
        notes_parts.append(data["notes"])

    task_info = await _create_task_from_webhook(
        db, tenant_id, key,
        title=task_title,
        description=" | ".join(notes_parts),
        source_app="sales",
        priority=data.get("priority", "medium"),
        deadline_str=data.get("deadline") or None,
        deadline_days=30,
        department_id=dept_id,
        tags=data.get("tags", []),
    )
    await db.commit()
    return {
        "message":        "External task and project created from sales lead.",
        "auto_generated": True,
        **task_info,
    }


# ── Field Tech handler ────────────────────────────────────────

async def _handle_field_tech(
    db: AsyncSession, tenant_id: uuid.UUID, key: WebhookApiKey,
    event_type: str, data: dict[str, Any],
) -> dict:
    from app.modules.all_modules import OutageIncident

    if event_type == "equipment.fault":
        title = data.get("title") or f"Equipment fault: {data.get('equipment_id', 'unknown')}"
        return await _handle_field_tech(
            db, tenant_id, key, "outage.detected",
            {**data, "title": title, "severity": data.get("severity", "warning")},
        )

    if event_type == "outage.detected":
        title = data.get("title")
        if not title:
            raise HTTPException(422, "data.title required for outage.detected")

        olt_ref = data.get("olt_reference")
        if olt_ref:
            duplicate = (await db.execute(
                select(OutageIncident).where(
                    OutageIncident.tenant_id     == tenant_id,
                    OutageIncident.olt_reference == olt_ref,
                    OutageIncident.status.in_(["active", "monitoring"]),
                )
            )).scalar_one_or_none()
            if duplicate:
                return {
                    "message":     "Duplicate: active outage already exists.",
                    "incident_id": str(duplicate.id),
                    "reference":   duplicate.reference,
                }

        n = (await db.execute(
            select(func.count()).select_from(OutageIncident)
            .where(OutageIncident.tenant_id == tenant_id)
        )).scalar_one()
        reference = f"OUT-{datetime.date.today().year}-{str(n + 1).zfill(3)}"

        region_id: uuid.UUID | None = None
        if data.get("region_id"):
            try:
                region_id = uuid.UUID(data["region_id"])
            except ValueError:
                pass

        reported_by: uuid.UUID | None = key.created_by
        if data.get("reported_by_user_id"):
            try:
                reported_by = uuid.UUID(data["reported_by_user_id"])
            except ValueError:
                pass
        if reported_by is None:
            raise HTTPException(
                422,
                "Cannot create outage: no reporter. "
                "Provide data.reported_by_user_id or ensure the webhook key has a creator.",
            )

        incident = OutageIncident(
            tenant_id=tenant_id,
            reference=reference,
            title=title,
            description=data.get("description"),
            severity=data.get("severity", "warning"),
            region_id=region_id,
            olt_reference=olt_ref,
            reported_by=reported_by,
        )
        db.add(incident)
        await db.flush()
        severity = data.get("severity", "warning")
        desc_parts = [f"Ref: {reference}", f"Severity: {severity}"]
        if data.get("description"):
            desc_parts.append(data["description"])
        task_info = await _create_task_from_webhook(
            db, tenant_id, key,
            title=f"Outage Response: {title}",
            description=". ".join(desc_parts),
            source_app="field",
            priority="critical" if severity == "critical" else "high",
            deadline_days=1,
        )
        await db.commit()
        return {
            "message":     "Outage incident created.",
            "incident_id": str(incident.id),
            "reference":   reference,
            **task_info,
        }

    elif event_type == "outage.resolved":
        reference = data.get("reference")
        if not reference:
            raise HTTPException(422, "data.reference required for outage.resolved")

        incident = (await db.execute(
            select(OutageIncident).where(
                OutageIncident.tenant_id == tenant_id,
                OutageIncident.reference == reference,
            )
        )).scalar_one_or_none()
        if not incident:
            raise HTTPException(404, f"Outage {reference!r} not found.")

        incident.status      = "resolved"
        incident.resolved_at = datetime.datetime.utcnow()
        await db.flush()
        await db.commit()
        return {"message": "Outage resolved.", "incident_id": str(incident.id)}

    else:
        raise HTTPException(422, f"Unknown Field Tech event: {event_type!r}")


# ── Inventory handler ─────────────────────────────────────────

async def _handle_inventory(
    db: AsyncSession, tenant_id: uuid.UUID, key: WebhookApiKey,
    event_type: str, data: dict[str, Any],
) -> dict:
    SUPPORTED = {"stock.depleted", "equipment.requested", "asset.missing"}
    if event_type not in SUPPORTED:
        raise HTTPException(422, f"Unknown Inventory event: {event_type!r}")

    default_titles = {
        "stock.depleted":      f"Restock required: {data.get('item_name', 'Unknown item')}",
        "equipment.requested": f"Equipment request: {data.get('item_name', 'Unknown item')}",
        "asset.missing":       f"Missing asset: {data.get('asset_tag', 'Unknown asset')}",
    }
    title = data.get("title") or default_titles[event_type]

    notes = [f"Event: {event_type}"]
    if data.get("quantity"):
        notes.append(f"Qty: {data['quantity']}")
    if data.get("location"):
        notes.append(f"Location: {data['location']}")
    if data.get("notes"):
        notes.append(data["notes"])

    task_info = await _create_task_from_webhook(
        db, tenant_id, key,
        title=title,
        description=" | ".join(notes),
        source_app="inventory",
        priority="high" if event_type == "asset.missing" else "medium",
        deadline_days=7,
    )
    await db.commit()
    return {"message": f"Inventory task created for {event_type}.", **task_info}


# ── Integration handler ───────────────────────────────────────

async def _handle_integration(
    db: AsyncSession, tenant_id: uuid.UUID, key: WebhookApiKey,
    event_type: str, data: dict[str, Any],
) -> dict:
    SUPPORTED = {"sync.failed", "api.error", "connection.lost"}
    if event_type not in SUPPORTED:
        raise HTTPException(422, f"Unknown Integration event: {event_type!r}")

    default_titles = {
        "sync.failed":     f"Sync failure: {data.get('integration_name', 'Unknown')}",
        "api.error":       f"API error: {data.get('integration_name', 'Unknown')}",
        "connection.lost": f"Connection lost: {data.get('integration_name', 'Unknown')}",
    }
    title = data.get("title") or default_titles[event_type]

    notes = [f"Event: {event_type}"]
    if data.get("error_message"):
        notes.append(f"Error: {data['error_message']}")
    if data.get("integration_name"):
        notes.append(f"Integration: {data['integration_name']}")
    if data.get("notes"):
        notes.append(data["notes"])

    task_info = await _create_task_from_webhook(
        db, tenant_id, key,
        title=title,
        description=" | ".join(notes),
        source_app="integration",
        priority="high",
        deadline_days=1,
    )
    await db.commit()
    return {"message": f"Integration task created for {event_type}.", **task_info}


# ── Coverage handler ──────────────────────────────────────────

async def _handle_coverage(
    db: AsyncSession, tenant_id: uuid.UUID, key: WebhookApiKey,
    event_type: str, data: dict[str, Any],
) -> dict:
    from app.modules.activity.service import timeline_writer
    from app.core.context import tenant_id_ctx

    if event_type not in ("coverage.expanded", "coverage.degraded"):
        raise HTTPException(422, f"Unknown Coverage event: {event_type!r}")

    region_id_raw = data.get("region_id")
    if not region_id_raw:
        raise HTTPException(422, "data.region_id required.")
    try:
        region_uuid = uuid.UUID(region_id_raw)
    except ValueError:
        raise HTTPException(422, "data.region_id must be a valid UUID.")

    description = data.get("description", "No description provided.")
    body = (
        f"Coverage expanded: {description}"
        if event_type == "coverage.expanded"
        else f"Coverage degradation reported: {description}"
    )

    ctx_token = tenant_id_ctx.set(tenant_id)
    try:
        await timeline_writer.write_system_event(
            db, entity_type="region", entity_id=region_uuid,
            body=body,
            meta={"source": "coverage_webhook", "event": event_type, **data},
        )
    finally:
        tenant_id_ctx.reset(ctx_token)

    await db.commit()
    return {"message": "Coverage event logged.", "region_id": region_id_raw}
