# ============================================================
# OPSYN NOTIFICATIONS SERVICE — app/modules/notifications/service.py
# Phase 5 enhanced: bulk department notifications, structured
# categories, related entity links, sender tracking.
# ============================================================

import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.all_modules import Notification
from app.core.database import AsyncSessionLocal


class NotificationService:

    async def create_notification(
        self,
        db:                    AsyncSession,
        recipient_id:          str,
        notif_type:            str,
        title:                 str,
        body:                  Optional[str] = None,
        action_url:            Optional[str] = None,
        tenant_id:             Optional[str] = None,
        notification_category: Optional[str] = None,
        sender_id:             Optional[str] = None,
        related_task_id:       Optional[str] = None,
        related_project_id:    Optional[str] = None,
        related_dept_id:       Optional[str] = None,
    ) -> None:
        """Create an in-app notification within an existing session."""
        notif = Notification(
            recipient_id=uuid.UUID(recipient_id),
            type=notif_type,
            title=title,
            body=body,
            action_url=action_url,
            notification_category=notification_category or notif_type,
            sender_id=uuid.UUID(sender_id) if sender_id else None,
            related_task_id=uuid.UUID(related_task_id) if related_task_id else None,
            related_project_id=uuid.UUID(related_project_id) if related_project_id else None,
            related_dept_id=uuid.UUID(related_dept_id) if related_dept_id else None,
        )
        if tenant_id:
            notif.tenant_id = uuid.UUID(tenant_id)
        db.add(notif)
        await db.flush()

    async def create_system_notification(
        self,
        recipient_id:          str,
        notif_type:            str,
        title:                 str,
        body:                  Optional[str] = None,
        action_url:            Optional[str] = None,
        tenant_id:             Optional[str] = None,
        notification_category: Optional[str] = None,
        related_task_id:       Optional[str] = None,
        related_project_id:    Optional[str] = None,
        related_dept_id:       Optional[str] = None,
    ) -> None:
        """Create an in-app notification using its own session (fire-and-forget)."""
        async with AsyncSessionLocal() as db:
            await self.create_notification(
                db=db,
                recipient_id=recipient_id,
                notif_type=notif_type,
                title=title,
                body=body,
                action_url=action_url,
                tenant_id=tenant_id,
                notification_category=notification_category or notif_type,
                related_task_id=related_task_id,
                related_project_id=related_project_id,
                related_dept_id=related_dept_id,
            )
            await db.commit()

    async def notify_department(
        self,
        db:                    AsyncSession,
        dept_id:               str,
        notif_type:            str,
        title:                 str,
        body:                  str,
        action_url:            Optional[str] = None,
        sender_id:             Optional[str] = None,
        related_task_id:       Optional[str] = None,
        related_project_id:    Optional[str] = None,
        exclude_user_ids:      Optional[list] = None,
    ) -> None:
        """Notify every active member of a department."""
        from app.modules.staff.models import User, StaffProfile

        members = (await db.execute(
            select(User)
            .join(StaffProfile, StaffProfile.user_id == User.id)
            .where(
                StaffProfile.department_id == uuid.UUID(dept_id),
                User.is_active             == True,  # noqa: E712
            )
        )).scalars().all()

        exclude = set(exclude_user_ids or [])
        for user in members:
            if str(user.id) in exclude:
                continue
            await self.create_notification(
                db=db,
                recipient_id=str(user.id),
                notif_type=notif_type,
                title=title,
                body=body,
                action_url=action_url,
                tenant_id=str(user.tenant_id),
                notification_category=notif_type,
                sender_id=sender_id,
                related_task_id=related_task_id,
                related_project_id=related_project_id,
                related_dept_id=dept_id,
            )


notification_service = NotificationService()


# ── Celery tasks ──────────────────────────────────────────────
from app.core.celery_app import celery_app


@celery_app.task(name="notifications.send_invite_email", bind=True, max_retries=3)
def send_invite_email(self, user_id: str, email: str, invite_token: str):
    """Send an invite email to a newly provisioned staff member."""
    from app.core.config import settings
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from jinja2 import Environment, FileSystemLoader
        import os

        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        env          = Environment(loader=FileSystemLoader(template_dir))
        template     = env.get_template("invite.html")
        invite_url   = f"{settings.FRONTEND_URL}/activate?token={invite_token}"
        html_body    = template.render(invite_url=invite_url, platform_name="Opsyn")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "You've been invited to Opsyn — Powered by SlimTech"
        msg["From"]    = f"{settings.FROM_NAME} <{settings.FROM_EMAIL}>"
        msg["To"]      = email
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.FROM_EMAIL, [email], msg.as_string())

    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="notifications.send_outage_alert", bind=True, max_retries=2)
def send_outage_alert(self, incident_id: str, title: str, severity: str):
    """Send outage alert notification to NOC team leads."""
    import structlog
    structlog.get_logger().info(
        "outage_alert_dispatched",
        incident_id=incident_id, severity=severity, title=title,
    )


@celery_app.task(name="notifications.send_onboarding_approved_email", bind=True, max_retries=3)
def send_onboarding_approved_email(self, email: str, candidate_name: str, invite_url: str):
    """Notify a newly approved candidate that their account has been provisioned."""
    from app.core.config import settings
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from jinja2 import Environment, FileSystemLoader
        import os

        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        env          = Environment(loader=FileSystemLoader(template_dir))
        template     = env.get_template("onboarding_approved.html")
        html_body    = template.render(
            candidate_name=candidate_name,
            invite_url=invite_url,
            platform_name="Opsyn",
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Your Opsyn account is ready — Powered by SlimTech"
        msg["From"]    = f"{settings.FROM_NAME} <{settings.FROM_EMAIL}>"
        msg["To"]      = email
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.FROM_EMAIL, [email], msg.as_string())

    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
