# ============================================================
# OPSYN TASK DEADLINE REMINDERS — app/tasks/task_reminders.py
# Phase 6.5: Celery beat task — runs daily at 08:00.
# Notifies assignees of tasks due within 24 hours.
# ============================================================

import asyncio
import datetime
from app.core.celery_app import celery_app


@celery_app.task(name="tasks.send_deadline_reminders", bind=True, max_retries=2)
def send_deadline_reminders(self):
    """Runs daily at 08:00 via Celery beat. Notifies assignees of upcoming deadlines."""
    try:
        asyncio.run(_send_reminders())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=300)


async def _send_reminders():
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.modules.tasks.models import Task
    from app.modules.notifications.service import notification_service

    async with AsyncSessionLocal() as db:
        tomorrow = datetime.datetime.utcnow() + datetime.timedelta(days=1)
        now      = datetime.datetime.utcnow()

        tasks = (await db.execute(
            select(Task).where(
                Task.deadline      >= now,
                Task.deadline      <= tomorrow,
                Task.is_deleted    == False,  # noqa: E712
                Task.pipeline_stage.notin_(["unit_done", "archive"]),
            )
        )).scalars().all()

        for task in tasks:
            if task.assignee_user_id:
                await notification_service.create_system_notification(
                    recipient_id=str(task.assignee_user_id),
                    notif_type="deadline_reminder",
                    title=f"Task due tomorrow: {task.title}",
                    body=f"Task {task.ticket_number} is due on {task.deadline.strftime('%d %b %Y')}.",
                    action_url=f"/tasks/{task.id}",
                    tenant_id=str(task.tenant_id),
                )
            if task.created_by and task.created_by != task.assignee_user_id:
                await notification_service.create_system_notification(
                    recipient_id=str(task.created_by),
                    notif_type="deadline_reminder",
                    title=f"Task you created is due tomorrow: {task.title}",
                    body=f"Task {task.ticket_number} is due on {task.deadline.strftime('%d %b %Y')}.",
                    action_url=f"/tasks/{task.id}",
                    tenant_id=str(task.tenant_id),
                )
