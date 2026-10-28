# ============================================================
# OPSYN CELERY TASK — Outage Customer Notifications
# app/tasks/customer_notifications.py
#
# Fires when an outage is logged/received.
# Loads matching auto-rules, sends via SMS (Termii) or Email.
# Logs all attempts to outage_notification_log.
# ============================================================

from __future__ import annotations

import asyncio
import uuid
import structlog

from app.core.celery_app import celery_app

log = structlog.get_logger(__name__)

SEVERITY_RANK = {"critical": 4, "high": 3, "warning": 2, "low": 1}


@celery_app.task(name="notifications.send_outage_notifications", bind=True, max_retries=2, default_retry_delay=60)
def send_outage_notifications(self, outage_id: str, tenant_id: str) -> None:
    """Evaluate auto-rules for an outage and send customer notifications."""
    try:
        asyncio.run(_send_notifications(outage_id, tenant_id))
    except Exception as exc:
        log.error("customer_notif_failed", outage_id=outage_id, error=str(exc))
        raise self.retry(exc=exc)


async def _send_notifications(outage_id: str, tenant_id: str) -> None:
    from app.tasks._db import make_task_session
    from app.modules.all_modules import OutageIncident
    from app.modules.shifts.models import OutageNotificationRule
    from sqlalchemy import select

    engine, db = await make_task_session()
    try:
        outage = (await db.execute(
            select(OutageIncident).where(OutageIncident.id == uuid.UUID(outage_id))
        )).scalar_one_or_none()

        if not outage:
            return

        rules = (await db.execute(
            select(OutageNotificationRule).where(
                OutageNotificationRule.tenant_id == uuid.UUID(tenant_id),
                OutageNotificationRule.is_auto.is_(True),
                OutageNotificationRule.is_active.is_(True),
            )
        )).scalars().all()

        outage_sev_rank = SEVERITY_RANK.get(outage.severity, 1)

        for rule in rules:
            rule_sev_rank = SEVERITY_RANK.get(rule.min_severity, 1)
            if outage_sev_rank < rule_sev_rank:
                continue
            if (outage.affected_subscribers or 0) < (rule.min_subscribers or 0):
                continue

            channels = rule.channels or ["sms"]
            msg = _render_template(rule.message_template or _default_template(), outage)

            for channel in channels:
                await _dispatch_channel(db, outage, rule, channel, msg)

        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
        await engine.dispose()


def _render_template(template: str, outage) -> str:
    return (template
            .replace("{reference}",   outage.reference or "")
            .replace("{title}",       outage.title or "")
            .replace("{severity}",    outage.severity or "")
            .replace("{status}",      outage.status or "")
            .replace("{olt}",         outage.olt_reference or "N/A")
            .replace("{subscribers}", str(outage.affected_subscribers or 0)))


def _default_template() -> str:
    return (
        "Opsyn Network Alert: {reference} — {title}. "
        "Severity: {severity}. Affected area: {olt}. "
        "We are working to resolve this. Apologies for the inconvenience."
    )


async def _dispatch_channel(db, outage, rule, channel: str, message: str) -> None:
    """Send notification via the specified channel and log the result."""
    from app.modules.shifts.models import OutageNotificationLog
    from app.core.config import settings

    status        = "sent"
    error_message = None

    try:
        if channel == "sms":
            await _send_sms(message, settings)
        elif channel == "email":
            await _send_email(message, outage, settings)
        elif channel == "whatsapp":
            await _send_whatsapp(message, settings)
        else:
            status        = "skipped"
            error_message = f"Unknown channel: {channel}"
    except Exception as exc:
        status        = "failed"
        error_message = str(exc)[:500]
        log.warning("customer_notif_channel_failed", channel=channel, outage=outage.reference, error=str(exc))

    log_entry = OutageNotificationLog(
        tenant_id     = outage.tenant_id,
        outage_id     = outage.id,
        rule_id       = rule.id,
        channel       = channel,
        recipient     = "broadcast",
        status        = status,
        error_message = error_message,
    )
    db.add(log_entry)
    await db.flush()


async def _send_sms(message: str, settings) -> None:
    """Send SMS via Termii API."""
    import httpx
    termii_key = getattr(settings, "TERMII_API_KEY", None)
    if not termii_key:
        log.info("sms_skipped_no_termii_key")
        return

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://api.ng.termii.com/api/sms/send/bulk",
            json={
                "api_key": termii_key,
                "to":      "broadcast",
                "from":    getattr(settings, "TERMII_SENDER_ID", "Opsyn"),
                "sms":     message,
                "type":    "plain",
                "channel": "generic",
            },
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Termii SMS failed: {resp.status_code} {resp.text[:200]}")


async def _send_whatsapp(message: str, settings) -> None:
    """Send WhatsApp via Termii API."""
    import httpx
    termii_key = getattr(settings, "TERMII_API_KEY", None)
    if not termii_key:
        return

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://api.ng.termii.com/api/sms/send",
            json={
                "api_key": termii_key,
                "to":      "broadcast",
                "from":    getattr(settings, "TERMII_SENDER_ID", "Opsyn"),
                "sms":     message,
                "type":    "plain",
                "channel": "whatsapp",
            },
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Termii WhatsApp failed: {resp.status_code} {resp.text[:200]}")


async def _send_email(message: str, outage, settings) -> None:
    """Send email notification via SMTP."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_host = getattr(settings, "SMTP_HOST", None)
    smtp_from = getattr(settings, "FROM_EMAIL", None)
    notif_to  = getattr(settings, "OUTAGE_NOTIFICATION_EMAIL", None)

    if not all([smtp_host, smtp_from, notif_to]):
        log.info("email_notif_skipped_no_smtp_config")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[{outage.severity.upper()}] Network Outage: {outage.reference}"
    msg["From"]    = f"Opsyn Alerts <{smtp_from}>"
    msg["To"]      = notif_to
    msg.attach(MIMEText(message, "plain"))

    with smtplib.SMTP(smtp_host, getattr(settings, "SMTP_PORT", 587)) as server:
        server.starttls()
        if getattr(settings, "SMTP_USER", None):
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(smtp_from, [notif_to], msg.as_string())
