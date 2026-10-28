# ============================================================
# OPSYN CAPACITY MONITOR — app/tasks/capacity_monitor.py
# Celery beat task: evaluate InfraMonitoringConfig thresholds,
# create InfraCapacityAlert rows, and optionally create Tasks
# for action_type='create_task' alert rules.
# ============================================================

import asyncio
import logging
import uuid
from datetime import datetime as _dt, timezone as _tz, timedelta

from celery import shared_task
from sqlalchemy import select, text

from app.modules.infrastructure.models import (
    InfrastructureNode, InfrastructureSite,
    InfraMonitoringConfig, InfraAlertRule,
    InfraCapacityAlert,
)

logger = logging.getLogger(__name__)

# Map operator strings to Python comparisons
_OPS = {
    "gt":  lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt":  lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "eq":  lambda a, b: a == b,
}


@shared_task(name="infrastructure.check_capacity", bind=True, max_retries=2)
def check_capacity_thresholds(self):
    try:
        asyncio.run(_run_checks())
    except Exception as exc:
        logger.exception("Capacity monitor failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)


async def _run_checks() -> None:
    from app.tasks._db import make_task_session

    engine, db = await make_task_session()
    try:
        configs = (await db.execute(
            select(InfraMonitoringConfig).where(InfraMonitoringConfig.is_active.is_(True))
        )).scalars().all()

        for cfg in configs:
            try:
                await _check_config(db, cfg)
            except Exception as exc:
                logger.error(
                    "Capacity check failed for config %s (tenant %s): %s",
                    cfg.id, cfg.tenant_id, exc,
                )

        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
        await engine.dispose()


async def _check_config(db, cfg: InfraMonitoringConfig) -> None:
    """Evaluate one monitoring config; fire alerts if thresholds crossed."""
    current_pct = await _get_utilisation_pct(db, cfg)
    if current_pct is None:
        return

    # Determine which threshold (if any) has been crossed
    severity = None
    threshold = None
    if current_pct >= cfg.critical_threshold_pct:
        severity  = "critical"
        threshold = cfg.critical_threshold_pct
    elif current_pct >= cfg.warn_threshold_pct:
        severity  = "warning"
        threshold = cfg.warn_threshold_pct

    if severity is None:
        return

    # Dedup: skip if an unresolved alert of same severity already exists
    # within the last check_interval_minutes
    cutoff = _dt.now(_tz.utc) - timedelta(minutes=cfg.check_interval_minutes)
    existing = (await db.execute(
        select(InfraCapacityAlert).where(
            InfraCapacityAlert.tenant_id  == cfg.tenant_id,
            InfraCapacityAlert.is_resolved.is_(False),
            InfraCapacityAlert.severity   == severity,
            InfraCapacityAlert.created_at >= cutoff,
            # match entity
            (InfraCapacityAlert.node_id == cfg.entity_id)
            if cfg.entity_type == "node"
            else (InfraCapacityAlert.site_id == cfg.entity_id),
        )
    )).scalars().first()
    if existing:
        return

    # Resolve entity details for message
    entity_name = cfg.entity_type
    site_id_val = None
    node_id_val = None
    if cfg.entity_type == "node":
        node = await db.get(InfrastructureNode, cfg.entity_id)
        entity_name = node.name if node else str(cfg.entity_id)
        node_id_val = cfg.entity_id
        if node and node.site_id:
            site_id_val = node.site_id
    elif cfg.entity_type == "site":
        site = await db.get(InfrastructureSite, cfg.entity_id)
        entity_name = site.name if site else str(cfg.entity_id)
        site_id_val = cfg.entity_id

    msg = (
        f"{severity.upper()}: {entity_name} utilisation at {current_pct}% "
        f"(threshold {threshold}%)"
    )

    # Check alert rules for action_type='create_task'
    linked_task_id = await _evaluate_alert_rules(
        db, cfg.tenant_id, current_pct, severity, entity_name,
    )

    alert = InfraCapacityAlert(
        tenant_id=cfg.tenant_id,
        site_id=site_id_val,
        node_id=node_id_val,
        alert_type="capacity",
        severity=severity,
        threshold_pct=threshold,
        current_pct=current_pct,
        message=msg,
        is_resolved=False,
        linked_task_id=linked_task_id,
    )
    db.add(alert)
    logger.info("Created %s capacity alert for %s (%d%%)", severity, entity_name, current_pct)


async def _get_utilisation_pct(db, cfg: InfraMonitoringConfig) -> int | None:
    """Return current utilisation % for the monitored entity."""
    if cfg.entity_type == "node":
        row = (await db.execute(
            text("""
                SELECT COALESCE(SUM(used_capacity), 0),
                       COALESCE(SUM(total_capacity), 1)
                FROM infra_ports
                WHERE tenant_id = :tid AND node_id = :eid
            """),
            {"tid": str(cfg.tenant_id), "eid": str(cfg.entity_id)},
        )).fetchone()
        if not row or row[1] == 0:
            return None
        return round(row[0] / row[1] * 100)

    elif cfg.entity_type == "site":
        row = (await db.execute(
            text("""
                SELECT COALESCE(SUM(p.used_capacity), 0),
                       COALESCE(SUM(p.total_capacity), 1)
                FROM infra_ports p
                JOIN infrastructure_nodes n ON n.id = p.node_id
                WHERE p.tenant_id = :tid AND n.site_id = :eid
            """),
            {"tid": str(cfg.tenant_id), "eid": str(cfg.entity_id)},
        )).fetchone()
        if not row or row[1] == 0:
            return None
        return round(row[0] / row[1] * 100)

    return None


async def _evaluate_alert_rules(
    db, tenant_id: uuid.UUID, current_pct: int, severity: str, entity_name: str
) -> uuid.UUID | None:
    """
    Evaluate InfraAlertRules for this tenant. If a matching rule has
    action_type='create_task', create a Task and return its id.
    Returns the first created task id, or None.
    """
    rules = (await db.execute(
        select(InfraAlertRule).where(
            InfraAlertRule.tenant_id == tenant_id,
            InfraAlertRule.is_active.is_(True),
        )
    )).scalars().all()

    for rule in rules:
        op_fn = _OPS.get(rule.operator)
        if not op_fn:
            continue
        field_value = current_pct if rule.condition_field == "utilisation_pct" else current_pct
        try:
            if not op_fn(float(field_value), float(rule.threshold_value)):
                continue
        except (TypeError, ValueError):
            continue

        if rule.action_type == "create_task":
            task_id = await _create_capacity_task(db, tenant_id, rule, entity_name, current_pct)
            return task_id

    return None


async def _create_capacity_task(
    db, tenant_id: uuid.UUID, rule: InfraAlertRule, entity_name: str, current_pct: int,
) -> uuid.UUID | None:
    """Create a Task row for this alert rule and return its id."""
    try:
        from app.modules.tasks.models import Task  # local import to avoid circular
        params      = rule.action_params or {}
        title       = params.get("title") or f"Capacity alert: {entity_name} at {current_pct}%"
        task_type   = params.get("task_type", "maintenance")
        priority    = params.get("priority", "high")
        description = (
            f"Auto-generated by alert rule '{rule.name}'.\n"
            f"Entity: {entity_name}\n"
            f"Utilisation: {current_pct}% (threshold: {float(rule.threshold_value):.0f}%)"
        )

        # Generate ticket number
        from sqlalchemy import text as _text
        result = await db.execute(
            _text(
                "SELECT COALESCE(MAX(CAST(RIGHT(ticket_number,4) AS INT)),0)+1 "
                "FROM tasks WHERE tenant_id=:tid"
            ),
            {"tid": str(tenant_id)},
        )
        seq = result.scalar_one()
        from datetime import date
        ticket = f"TSK-{date.today().year}-{seq:04d}"

        task = Task(
            tenant_id=tenant_id,
            title=title,
            description=description,
            task_type=task_type,
            priority=priority,
            status="new",
            ticket_number=ticket,
        )
        db.add(task)
        await db.flush()
        return task.id
    except Exception as exc:
        logger.warning("Failed to create capacity task: %s", exc)
        return None
