# ============================================================
# OPSYN CELERY TASK — SLA Breach Checker
# app/tasks/sla_checker.py
#
# Runs every 5 minutes via Celery Beat.
# Finds outages approaching or past their SLA deadline and:
#   - At 80% elapsed: warning timeline entry + assignee notification
#   - At 100% (past deadline): sets breached_sla=True + notifies NOC Manager
# ============================================================

from __future__ import annotations

import asyncio
import datetime
import structlog

from app.core.celery_app import celery_app
from app.modules.tasks.models import Task  # noqa: F401 — registers tasks table in SA metadata
from app.modules.tenants.models import Tenant  # noqa: F401 — registers tenants table so outage_incidents FK resolves

log = structlog.get_logger(__name__)


@celery_app.task(name="smartolt.check_sla_breaches", bind=True, max_retries=2, default_retry_delay=60)
def check_sla_breaches(self) -> None:
    """Check all active outages for SLA breaches and warnings."""
    try:
        asyncio.run(_check_all())
    except Exception as exc:
        log.error("sla_check_failed", error=str(exc))
        raise self.retry(exc=exc)


async def _check_all() -> None:
    from app.modules.all_modules import OutageIncident
    from app.tasks._db import make_task_session
    from app.modules.activity.service import timeline_writer
    from app.modules.notifications.service import notification_service
    from sqlalchemy import select
    from app.core.context import tenant_id_ctx

    now = datetime.datetime.utcnow()

    engine, db = await make_task_session()
    try:
        # Outages with sla_deadline set, not yet resolved, not yet breached
        active = (await db.execute(
            select(OutageIncident).where(
                OutageIncident.sla_deadline.isnot(None),
                OutageIncident.status != "resolved",
                OutageIncident.breached_sla.is_(False),
            )
        )).scalars().all()

        for inc in active:
            deadline: datetime.datetime = inc.sla_deadline.replace(tzinfo=None) if inc.sla_deadline.tzinfo else inc.sla_deadline
            created:  datetime.datetime = inc.created_at.replace(tzinfo=None) if inc.created_at.tzinfo else inc.created_at

            total_secs   = max((deadline - created).total_seconds(), 1)
            elapsed_secs = (now - created).total_seconds()
            pct_elapsed  = elapsed_secs / total_secs

            tenant_id_ctx.set(inc.tenant_id)

            if now >= deadline:
                # Full breach
                inc.breached_sla = True
                await timeline_writer.write_system_event(
                    db=db,
                    entity_type="outage",
                    entity_id=inc.id,
                    body=f"SLA BREACHED — incident {inc.reference} exceeded {int(total_secs // 60)}-minute SLA.",
                    meta={"sla_event": "breach"},
                )
                await _notify_managers(db, inc, notification_service, "breach")
                log.warning("sla_breached", incident=inc.reference, tenant=str(inc.tenant_id))

            elif pct_elapsed >= 0.80:
                # 80% warning — only write once per incident (check timeline would be ideal;
                # for simplicity we use a meta key in the incident itself via breached_sla=False)
                # We track warning by checking if a "sla_warning" timeline entry exists
                already_warned = await _has_sla_warning(db, inc.id)
                if not already_warned:
                    remaining = int((deadline - now).total_seconds() // 60)
                    await timeline_writer.write_system_event(
                        db=db,
                        entity_type="outage",
                        entity_id=inc.id,
                        body=f"SLA Warning — {remaining} minutes remaining for incident {inc.reference}.",
                        meta={"sla_event": "warning"},
                    )
                    if inc.reported_by:
                        await notification_service.create_notification(
                            db=db,
                            recipient_id=str(inc.reported_by),
                            notif_type="outage_warning",
                            title=f"SLA Warning: {inc.reference}",
                            body=f"{remaining} minutes remaining before SLA breach.",
                            action_url=f"/outage/{inc.id}",
                            tenant_id=str(inc.tenant_id),
                        )

        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
        await engine.dispose()


async def _has_sla_warning(db, incident_id) -> bool:
    """Check if a sla_event=warning entry already exists in the timeline."""
    from sqlalchemy import text
    row = (await db.execute(
        text("""
            SELECT 1 FROM activity_timeline
            WHERE entity_type = 'outage'
              AND entity_id   = :eid
              AND meta        @> CAST(:meta AS jsonb)
            LIMIT 1
        """),
        {"eid": str(incident_id), "meta": '{"sla_event":"warning"}'},
    )).fetchone()
    return row is not None


async def _notify_managers(db, inc, notification_service, event: str) -> None:
    """Notify all Manager+ users about an SLA event."""
    from app.modules.staff.models import User
    from app.modules.roles.models import Role
    from sqlalchemy import select

    managers = (await db.execute(
        select(User.id).join(Role, Role.id == User.role_id).where(
            User.tenant_id == inc.tenant_id,
            User.is_active.is_(True),
            Role.level >= 4,
        )
    )).scalars().all()

    label = "BREACHED" if event == "breach" else "Warning"
    for uid in managers:
        await notification_service.create_notification(
            db=db,
            recipient_id=str(uid),
            notif_type="outage_sla_breach",
            title=f"SLA {label}: {inc.reference}",
            body=f"Incident {inc.reference} (severity: {inc.severity}) has breached its SLA." if event == "breach"
                 else f"Incident {inc.reference} is approaching its SLA deadline.",
            action_url=f"/outage/{inc.id}",
            tenant_id=str(inc.tenant_id),
        )
