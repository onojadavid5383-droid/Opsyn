# ============================================================
# OPSYN STAFF EFFICIENCY SCORER — app/tasks/staff_efficiency.py
# Celery beat task (hourly): computes efficiency_score per
# staff member and writes it back to staff_profiles.
#
# Score formula (0–100):
#   40% tasks_done_pct  (done tasks / assigned tasks, last 30d)
#   30% sla_adherence   (tasks done before due_date / done tasks)
#   30% resolution_speed (1 - avg_hours_to_close / 72h, clamped 0-1)
# ============================================================

import asyncio
import logging
from datetime import datetime as _dt, timezone as _tz, timedelta

from celery import shared_task
from sqlalchemy import select, text

from app.modules.staff.models import StaffProfile

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 30


@shared_task(name="staff.score_efficiency", bind=True, max_retries=2)
def score_staff_efficiency(self):
    try:
        asyncio.run(_score_all())
    except Exception as exc:
        logger.exception("Staff efficiency scoring failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)


async def _score_all() -> None:
    from app.tasks._db import make_task_session

    engine, db = await make_task_session()
    try:
        # Fetch all active staff profiles with their user_id / tenant_id
        profiles = (await db.execute(
            select(StaffProfile).where(StaffProfile.status == "active")
        )).scalars().all()

        now = _dt.now(_tz.utc)
        cutoff = now - timedelta(days=LOOKBACK_DAYS)

        for profile in profiles:
            try:
                score = await _compute_score(db, profile.user_id, profile.tenant_id, cutoff)
                profile.efficiency_score       = round(score, 2)
                profile.efficiency_computed_at = now
            except Exception as exc:
                logger.warning(
                    "Failed scoring staff %s: %s", profile.user_id, exc
                )

        await db.commit()
        logger.info("Staff efficiency scoring complete -- %d profiles updated", len(profiles))
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
        await engine.dispose()


async def _compute_score(db, user_id, tenant_id, cutoff: _dt) -> float:
    """Return a 0–100 efficiency score for one staff member."""
    row = (await db.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'done')                         AS done_count,
                COUNT(*)                                                          AS total_count,
                COUNT(*) FILTER (WHERE status = 'done'
                                   AND due_date IS NOT NULL
                                   AND updated_at <= due_date)                   AS on_time_count,
                AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 3600.0)
                    FILTER (WHERE status = 'done')                               AS avg_hours
            FROM tasks
            WHERE tenant_id = :tid
              AND assigned_to = :uid
              AND created_at >= :cutoff
        """),
        {"tid": str(tenant_id), "uid": str(user_id), "cutoff": cutoff},
    )).fetchone()

    if not row or row[1] == 0:
        return 0.0

    done_count   = int(row[0] or 0)
    total_count  = int(row[1] or 0)
    on_time      = int(row[2] or 0)
    avg_hours    = float(row[3] or 72.0)

    # Component 1: task completion rate (0–1)
    tasks_done_pct = done_count / max(total_count, 1)

    # Component 2: SLA adherence (0–1)
    sla_adherence = on_time / max(done_count, 1) if done_count > 0 else 0.0

    # Component 3: resolution speed — normalise against 72h baseline (0–1)
    speed = max(0.0, 1.0 - avg_hours / 72.0)

    score = (tasks_done_pct * 40) + (sla_adherence * 30) + (speed * 30)
    return min(100.0, max(0.0, score))
