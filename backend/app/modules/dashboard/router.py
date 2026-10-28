# ============================================================
# OPSYN DASHBOARD ROUTER — app/modules/dashboard/router.py
# Real-time aggregated KPIs for the command center
# ============================================================

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.modules.staff.models import User

router = APIRouter()


@router.get("/summary")
async def dashboard_summary(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(get_current_user),
):
    """
    Aggregated KPIs for the dashboard command center.
    All counts are tenant-scoped where applicable.
    """
    tid = caller.tenant_id

    # ── Staff ────────────────────────────────────────────────
    staff_total = (await db.execute(
        select(func.count()).select_from(User).where(
            User.tenant_id == tid, User.is_active == True
        )
    )).scalar_one()

    pending_onboarding = (await db.execute(
        text("""
            SELECT COUNT(*) FROM staff_onboarding_requests
            WHERE approval_status = 'pending'
        """)
    )).scalar_one()

    # ── Tasks ────────────────────────────────────────────────
    from app.modules.tasks.router import Task
    import datetime

    now   = datetime.datetime.utcnow()
    today = now.date()

    open_tasks = (await db.execute(
        select(func.count()).select_from(Task).where(
            Task.status.notin_(["done", "cancelled"])
        )
    )).scalar_one()

    overdue_tasks = (await db.execute(
        select(func.count()).select_from(Task).where(
            Task.deadline < now,
            Task.status.notin_(["done", "cancelled"]),
        )
    )).scalar_one()

    today_tasks = (await db.execute(
        select(func.count()).select_from(Task).where(
            func.date(Task.deadline) == today,
            Task.status.notin_(["done", "cancelled"]),
        )
    )).scalar_one()

    # ── Outages ──────────────────────────────────────────────
    from app.modules.all_modules import OutageIncident
    live_outages = (await db.execute(
        select(func.count()).select_from(OutageIncident).where(
            OutageIncident.tenant_id == tid,
            OutageIncident.status.in_(["active", "monitoring"]),
        )
    )).scalar_one()

    outages_today = (await db.execute(
        select(func.count()).select_from(OutageIncident).where(
            OutageIncident.tenant_id == tid,
            func.date(OutageIncident.created_at) == today,
        )
    )).scalar_one()

    # ── Notifications ────────────────────────────────────────
    from app.modules.all_modules import Notification
    unread_notifications = (await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.recipient_id == caller.id,
            Notification.is_read == False,
        )
    )).scalar_one()

    # ── Infrastructure ───────────────────────────────────────
    from app.modules.infrastructure.models import InfrastructureNode
    total_nodes = (await db.execute(
        select(func.count()).select_from(InfrastructureNode).where(
            InfrastructureNode.tenant_id == tid,
        )
    )).scalar_one()
    active_nodes = (await db.execute(
        select(func.count()).select_from(InfrastructureNode).where(
            InfrastructureNode.tenant_id == tid,
            InfrastructureNode.status == "active",
        )
    )).scalar_one()

    network_uptime_pct = (
        round((active_nodes / total_nodes) * 100, 1) if total_nodes > 0 else 100.0
    )

    # ── Projects ─────────────────────────────────────────────
    from app.modules.projects.models import Project
    active_projects = (await db.execute(
        select(func.count()).select_from(Project).where(
            Project.tenant_id == tid,
            Project.status == "active",
        )
    )).scalar_one()

    return {
        "success": True,
        "data": {
            "staff": {
                "total":               staff_total,
                "pending_onboarding":  pending_onboarding,
            },
            "tasks": {
                "open":    open_tasks,
                "overdue": overdue_tasks,
                "today":   today_tasks,
            },
            "outages": {
                "live":  live_outages,
                "today": outages_today,
            },
            "infrastructure": {
                "total_nodes":          total_nodes,
                "active_nodes":         active_nodes,
                "network_uptime_pct":   network_uptime_pct,
            },
            "projects": {
                "active": active_projects,
            },
            "notifications": {
                "unread": unread_notifications,
            },
        }
    }
