# ============================================================
# OPSYN SMARTOLT EVENT HANDLER — 7-step pipeline
# app/modules/smartolt/handler.py
# ============================================================

from __future__ import annotations

import datetime
import hashlib
import hmac
import logging
import uuid
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.smartolt.models import SmartOLTConfig, SmartOLTOltMap
from app.core.context import tenant_id_ctx

log = logging.getLogger("opsyn.smartolt")


# SLA minutes by severity
SLA_MINUTES: dict[str, int] = {
    "critical": 60,
    "high":     180,
    "warning":  480,
    "low":      1440,
}


def verify_smartolt_signature(secret: str, raw_body: bytes, signature: str) -> bool:
    """Verify SmartOLT HMAC-SHA256 webhook signature (sha256=<hex>)."""
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


async def handle_smartolt_event(
    db:        AsyncSession,
    tenant_id: uuid.UUID,
    payload:   dict[str, Any],
    config:    SmartOLTConfig,
) -> dict[str, Any] | None:
    """
    Process a SmartOLT alarm event through the 7-step pipeline.
    Returns serialised OutageIncident dict or None if deduplicated.
    """
    # ── Imports (deferred to avoid circular) ────────────────
    from app.modules.all_modules import OutageIncident
    from app.modules.activity.service import timeline_writer
    from app.modules.notifications.service import notification_service
    from app.modules.staff.models import User

    # ── Step 1: event type guard ─────────────────────────────
    event_type = payload.get("event_type", "alarm")
    if event_type not in ("alarm", "fault", "outage", "olt_down"):
        return None

    # ── Step 2: Deduplicate by event_id ─────────────────────
    event_id = payload.get("event_id") or payload.get("alarm_id")
    if event_id:
        existing = (await db.execute(
            select(OutageIncident).where(
                OutageIncident.smartolt_event_id == str(event_id),
                OutageIncident.tenant_id == tenant_id,
            )
        )).scalar_one_or_none()
        if existing:
            return None  # Already processed — idempotent

    # ── Step 3: Map OLT → region ─────────────────────────────
    olt_id      = str(payload.get("olt_id", ""))
    olt_name    = payload.get("olt_name") or olt_id
    region_id: uuid.UUID | None = None

    if olt_id:
        mapping = (await db.execute(
            select(SmartOLTOltMap).where(
                SmartOLTOltMap.tenant_id == tenant_id,
                SmartOLTOltMap.smartolt_olt_id == olt_id,
                SmartOLTOltMap.is_active.is_(True),
            )
        )).scalar_one_or_none()
        if mapping:
            region_id = mapping.region_id

    # ── Step 4: Classify severity ────────────────────────────
    affected_count = int(payload.get("affected_subscribers", 0))
    thresholds = config.severity_thresholds or {}
    crit_t  = thresholds.get("critical", 200)
    high_t  = thresholds.get("high",     50)
    warn_t  = thresholds.get("warning",  10)

    if affected_count >= crit_t:
        severity = "critical"
    elif affected_count >= high_t:
        severity = "high"
    elif affected_count >= warn_t:
        severity = "warning"
    else:
        severity = "low"

    # Override if payload explicitly sets severity
    if payload.get("severity") in ("critical", "high", "warning", "low"):
        severity = payload["severity"]

    # ── Step 5: Affected customers ───────────────────────────
    affected_customer_ids = payload.get("affected_customer_ids") or []

    # ── Step 6: Find on-call NOC (lowest active outage load) ─
    reporter_id = await _find_oncall_noc(db, tenant_id, region_id)
    if reporter_id is None:
        # Fallback: system user (first admin in tenant)
        admin = (await db.execute(
            select(User).where(User.tenant_id == tenant_id, User.is_active.is_(True))
            .order_by(User.created_at)
            .limit(1)
        )).scalar_one_or_none()
        if admin:
            reporter_id = admin.id
        else:
            return None  # No user to own the incident

    # ── Step 7: Create OutageIncident + Task + timeline ──────
    # Reference: OUT-YYYY-NNN (tenant-scoped)
    year  = datetime.date.today().year
    count = (await db.execute(
        select(func.count()).select_from(OutageIncident)
        .where(OutageIncident.tenant_id == tenant_id)
    )).scalar_one()
    reference = f"OUT-{year}-{str(count + 1).zfill(3)}"

    title = payload.get("title") or f"SmartOLT Alarm — {olt_name}"
    now   = datetime.datetime.utcnow()
    sla_minutes  = SLA_MINUTES.get(severity, 480)
    sla_deadline = now + datetime.timedelta(minutes=sla_minutes)

    incident = OutageIncident(
        tenant_id             = tenant_id,
        reference             = reference,
        title                 = title,
        description           = payload.get("description") or payload.get("alarm_message"),
        severity              = severity,
        status                = "active",
        region_id             = region_id,
        olt_reference         = olt_id or payload.get("olt_reference"),
        reported_by           = reporter_id,
        source                = "smartolt",
        smartolt_event_id     = str(event_id) if event_id else None,
        affected_customer_ids = affected_customer_ids,
        affected_subscribers  = affected_count,
        sla_deadline          = sla_deadline,
        breached_sla          = False,
    )
    db.add(incident)
    await db.flush()

    # Create linked task
    task = await _create_linked_task(db, tenant_id, incident, reporter_id)
    if task:
        incident.linked_task_id = task.id
        await db.flush()

    # Timeline entry
    tenant_id_ctx.set(tenant_id)
    await timeline_writer.write_system_event(
        db=db,
        entity_type="outage",
        entity_id=incident.id,
        body=f"SmartOLT alarm received. Severity: {severity}. Affected subscribers: {affected_count}. SLA deadline: {sla_deadline.strftime('%Y-%m-%d %H:%M')} UTC.",
        meta={"source": "smartolt", "event_id": str(event_id) if event_id else None},
    )

    # Notify NOC staff about critical/high incidents
    if severity in ("critical", "high"):
        await _notify_noc_team(db, tenant_id, incident, reporter_id, notification_service)

    # Step 7: Fire customer notifications if any auto-rules match
    from app.core.celery_app import celery_app as _celery
    _celery.send_task(
        "notifications.send_outage_notifications",
        args=[str(incident.id), str(tenant_id)],
    )

    return _serialize(incident)


async def _find_oncall_noc(
    db: AsyncSession, tenant_id: uuid.UUID, region_id: uuid.UUID | None
) -> uuid.UUID | None:
    """Find NOC operator with fewest active outages (lowest load)."""
    from app.modules.all_modules import OutageIncident
    from app.modules.staff.models import StaffProfile, User
    from app.modules.roles.models import Role

    # NOC role level = 2; find active users with noc in their role name
    q = (
        select(User.id)
        .join(StaffProfile, StaffProfile.user_id == User.id)
        .join(Role, Role.id == User.role_id)
        .where(
            User.tenant_id  == tenant_id,
            User.is_active.is_(True),
            Role.level == 2,
        )
        .order_by(
            select(func.count())
            .select_from(OutageIncident)
            .where(
                OutageIncident.reported_by == User.id,
                OutageIncident.status == "active",
            )
            .correlate(User)
            .scalar_subquery()
        )
        .limit(1)
    )
    row = (await db.execute(q)).fetchone()
    return row[0] if row else None


async def _create_linked_task(
    db: AsyncSession, tenant_id: uuid.UUID, incident: Any, assignee_id: uuid.UUID
) -> Any | None:
    """Create a Task linked to this outage incident."""
    try:
        from app.modules.tasks.models import Task
        from sqlalchemy import select, func

        year  = datetime.date.today().year
        count = (await db.execute(
            select(func.count()).select_from(Task)
            .where(Task.tenant_id == tenant_id)
        )).scalar_one()
        ticket = f"TSK-{year}-{str(count + 1).zfill(4)}"

        task = Task(
            tenant_id   = tenant_id,
            title       = f"Investigate: {incident.title}",
            description = f"Outage incident {incident.reference} — severity {incident.severity}. Auto-created by SmartOLT integration.",
            status      = "new",
            assignee_user_id = assignee_id,
            ticket_number = ticket,
        )
        db.add(task)
        await db.flush()
        return task
    except Exception:
        log.exception(
            "smartolt_linked_task_failed",
            extra={
                "tenant_id":         str(tenant_id),
                "incident_reference": getattr(incident, "reference", None),
                "assignee_id":       str(assignee_id),
            },
        )
        return None


async def _notify_noc_team(
    db: AsyncSession, tenant_id: uuid.UUID, incident: Any, reporter_id: uuid.UUID, notification_service: Any
) -> None:
    """Notify all active NOC-level users about a critical/high incident."""
    from app.modules.staff.models import User
    from app.modules.roles.models import Role

    noc_users = (await db.execute(
        select(User.id)
        .join(Role, Role.id == User.role_id)
        .where(
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
            Role.level >= 2,
            Role.level <= 3,
        )
    )).scalars().all()

    for uid in noc_users:
        await notification_service.create_notification(
            db=db,
            recipient_id=str(uid),
            notif_type="outage_critical",
            title=f"[{incident.severity.upper()}] {incident.title}",
            body=f"Incident {incident.reference} · {incident.affected_subscribers} subscribers affected · SLA: {incident.sla_deadline.strftime('%H:%M UTC') if incident.sla_deadline else 'N/A'}",
            action_url=f"/outage/{incident.id}",
            tenant_id=str(tenant_id),
        )


def _serialize(o: Any) -> dict[str, Any]:
    return {
        "id":                   str(o.id),
        "reference":            o.reference,
        "title":                o.title,
        "description":          o.description,
        "severity":             o.severity,
        "status":               o.status,
        "olt_reference":        o.olt_reference,
        "source":               o.source,
        "affected_subscribers": o.affected_subscribers,
        "sla_deadline":         o.sla_deadline.isoformat() if o.sla_deadline else None,
        "breached_sla":         o.breached_sla,
        "linked_task_id":       str(o.linked_task_id) if o.linked_task_id else None,
        "resolved_at":          o.resolved_at.isoformat() if o.resolved_at else None,
        "created_at":           o.created_at.isoformat(),
    }
