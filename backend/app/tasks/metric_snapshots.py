# ============================================================
# OPSYN METRIC SNAPSHOTS — app/tasks/metric_snapshots.py
# Celery beat task (hourly): record point-in-time operational ratios into
# ops_metric_snapshots so GET /reports/trends can chart them over time.
#
#   node_availability_pct  active infrastructure_nodes / all nodes
#   port_utilisation_pct   SUM(infra_ports.used_capacity) / SUM(total_capacity)
#
# A tenant with no nodes (or no port capacity) gets no row for that metric:
# 0/0 is "not measurable", not 100% — the dashboard's live figure reports
# 100% in that case, which is exactly the misleading value trends must avoid.
#
# Runs with no app.tenant_id set, so the tenant_isolation RLS policy admits
# every tenant's rows (same as capacity_monitor.py); each row written carries
# its own tenant_id explicitly.
# ============================================================

import asyncio
import logging

from celery import shared_task
from sqlalchemy import text

logger = logging.getLogger(__name__)

# metric_key → query returning (tenant_id, numerator, denominator)
_SNAPSHOT_QUERIES: dict[str, str] = {
    "node_availability_pct": """
        SELECT tenant_id,
               COUNT(*) FILTER (WHERE status = 'active') AS num,
               COUNT(*)                                   AS den
        FROM infrastructure_nodes
        GROUP BY tenant_id
    """,
    "port_utilisation_pct": """
        SELECT tenant_id,
               COALESCE(SUM(used_capacity), 0)  AS num,
               COALESCE(SUM(total_capacity), 0) AS den
        FROM infra_ports
        WHERE status = 'active'
        GROUP BY tenant_id
    """,
}


@shared_task(name="reports.capture_metric_snapshots", bind=True, max_retries=2)
def capture_metric_snapshots(self):
    try:
        asyncio.run(_capture())
    except Exception as exc:
        logger.exception("Metric snapshot capture failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)


async def _capture() -> None:
    from app.tasks._db import make_task_session

    engine, db = await make_task_session()
    try:
        written = 0
        for metric_key, query in _SNAPSHOT_QUERIES.items():
            for tenant_id, num, den in (await db.execute(text(query))).all():
                if not den:
                    continue
                await db.execute(
                    text("""
                        INSERT INTO ops_metric_snapshots
                            (tenant_id, metric_key, value, numerator, denominator)
                        VALUES (:tid, :key, :value, :num, :den)
                    """),
                    {
                        "tid": tenant_id, "key": metric_key,
                        "value": round(num / den * 100, 3),
                        "num": int(num), "den": int(den),
                    },
                )
                written += 1
        await db.commit()
        logger.info("Captured %d metric snapshot rows", written)
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
        await engine.dispose()
