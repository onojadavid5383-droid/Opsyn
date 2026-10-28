# ============================================================
# OPSYN PROJECT STAGE PUSHED BACK HANDLER
# app/events/handlers/project_stage_pushed_back.py
# ============================================================

from __future__ import annotations
import logging

log = logging.getLogger("opsyn.events")


async def handle_project_stage_pushed_back(event_data: dict) -> None:
    """
    Notify users in the previous (receiving) department when a stage is pushed back.

    event_data keys:
      project_id, project_name, from_stage_name, to_stage_name,
      to_department_id, reason, pushed_back_by_name
    """
    project_id   = event_data.get("project_id", "")
    project_name = event_data.get("project_name", "")
    from_stage   = event_data.get("from_stage_name", "")
    to_dept_id   = event_data.get("to_department_id")
    reason       = event_data.get("reason", "No reason provided")
    pushed_by    = event_data.get("pushed_back_by_name", "Someone")

    log.info(
        "event.project_stage_pushed_back project=%s from=%s dept=%s",
        project_id, from_stage, to_dept_id,
    )

    if not to_dept_id or not project_id:
        return

    try:
        from app.core.database import AsyncSessionLocal
        from app.modules.notifications.service import notification_service
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                text("""
                    SELECT u.id, u.tenant_id
                    FROM users u
                    JOIN staff_profiles sp ON sp.user_id = u.id
                    WHERE sp.department_id = :dept_id
                      AND sp.status = 'active'
                      AND u.is_active = true
                """),
                {"dept_id": to_dept_id},
            )).fetchall()

            for row in rows:
                await notification_service.create_notification(
                    db=db,
                    recipient_id=str(row[0]),
                    tenant_id=str(row[1]) if row[1] else None,
                    notif_type="pipeline_pushed_back",
                    title=f"Project returned: {project_name}",
                    body=(
                        f"{pushed_by} returned '{project_name}' from {from_stage}."
                        f" Reason: {reason}"
                    ),
                    action_url=f"/projects/{project_id}/pipeline",
                )
            await db.commit()

    except Exception as exc:
        log.error("project_stage_pushback_notification_failed project=%s error=%s", project_id, exc)
