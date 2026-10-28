# ============================================================
# OPSYN CELERY APP — app/core/celery_app.py
# Task queue for async email dispatch and notifications
# ============================================================

from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "opsyn",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.modules.notifications.service",
        "app.tasks.smartolt_polling",
        "app.tasks.sla_checker",
        "app.tasks.customer_notifications",
        "app.tasks.infrastructure_sync",
        "app.tasks.capacity_monitor",
        "app.tasks.staff_efficiency",
        "app.tasks.task_reminders",
        "app.tasks.fttx_design_run",
        "app.tasks.metric_snapshots",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    beat_schedule={
        "poll-smartolt-alarms": {
            "task":     "smartolt.poll_alarms",
            "schedule": 60.0,
        },
        "check-sla-breaches": {
            "task":     "smartolt.check_sla_breaches",
            "schedule": 300.0,
        },
        "sync-smartolt-ports": {
            "task":     "infrastructure.sync_smartolt_ports",
            "schedule": 900.0,
        },
        "check-capacity-thresholds": {
            "task":     "infrastructure.check_capacity",
            "schedule": 300.0,
        },
        "score-staff-efficiency": {
            "task":     "staff.score_efficiency",
            "schedule": 3600.0,
        },
        "send-task-deadline-reminders": {
            "task":     "tasks.send_deadline_reminders",
            "schedule": 86400.0,
        },
        "capture-metric-snapshots": {
            "task":     "reports.capture_metric_snapshots",
            "schedule": 3600.0,
        },
    },
)
