# ============================================================
# OPSYN CELERY TASK — SmartOLT Alarm Polling
# app/tasks/smartolt_polling.py
#
# Runs every 60 seconds via Celery Beat.
# Fetches current alarms from SmartOLT API for each configured
# tenant, compares against Redis-cached alarm IDs, and fires
# handle_smartolt_event() for any new alarms.
# ============================================================

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import structlog

from app.core.celery_app import celery_app

log = structlog.get_logger(__name__)


@celery_app.task(name="smartolt.poll_alarms", bind=True, max_retries=2, default_retry_delay=30)
def poll_smartolt_alarms(self) -> None:
    """Poll SmartOLT for new alarms across all tenants with polling enabled."""
    try:
        asyncio.run(_poll_all_tenants())
    except Exception as exc:
        log.error("smartolt_poll_failed", error=str(exc))
        raise self.retry(exc=exc)


async def _poll_all_tenants() -> None:
    from app.modules.smartolt.models import SmartOLTConfig
    from app.tasks._db import make_task_session
    from sqlalchemy import select

    engine, db = await make_task_session()
    try:
        configs = (await db.execute(
            select(SmartOLTConfig).where(SmartOLTConfig.polling_enabled.is_(True))
        )).scalars().all()
        await db.close()

        for config in configs:
            try:
                await _poll_tenant(config, engine)
            except Exception as exc:
                log.error("smartolt_tenant_poll_failed", tenant_id=str(config.tenant_id), error=str(exc))
    finally:
        await engine.dispose()


async def _poll_tenant(config: Any, engine) -> None:
    from app.core.redis_client import redis_pool
    from app.modules.smartolt.models import SmartOLTOltMap
    from app.modules.smartolt.handler import handle_smartolt_event
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    tenant_id   = config.tenant_id
    api_url     = (config.api_url or "https://app.smartolt.com").rstrip("/")
    api_key     = config.api_key
    if not api_key:
        return

    async with Session() as db:
        olt_maps = (await db.execute(
            select(SmartOLTOltMap).where(
                SmartOLTOltMap.tenant_id == tenant_id,
                SmartOLTOltMap.is_active.is_(True),
            )
        )).scalars().all()

    redis_key = f"smartolt:known_alarms:{tenant_id}"

    async with httpx.AsyncClient(timeout=15) as client:
        for olt_map in olt_maps:
            try:
                resp = await client.get(
                    f"{api_url}/api/v1/olts/{olt_map.smartolt_olt_id}/alarms",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code != 200:
                    continue

                alarms: list[dict] = resp.json().get("alarms", [])
                redis_client = redis_pool.client

                # Load known alarm IDs from Redis
                raw_known = await redis_client.get(redis_key)
                known_ids: set[str] = set(json.loads(raw_known)) if raw_known else set()

                new_alarms = [a for a in alarms if str(a.get("alarm_id", "")) not in known_ids]

                for alarm in new_alarms:
                    payload = {
                        "event_type":            "alarm",
                        "event_id":              alarm.get("alarm_id"),
                        "olt_id":                olt_map.smartolt_olt_id,
                        "olt_name":              olt_map.olt_name,
                        "title":                 alarm.get("description") or f"Alarm on {olt_map.olt_name}",
                        "description":           alarm.get("detail"),
                        "severity":              alarm.get("severity"),
                        "affected_subscribers":  alarm.get("affected_count", 0),
                        "affected_customer_ids": alarm.get("customer_ids", []),
                    }
                    async with Session() as db:
                        await handle_smartolt_event(db, tenant_id, payload, config)
                        await db.commit()

                # Update Redis cache with all current alarm IDs
                all_ids = [str(a.get("alarm_id", "")) for a in alarms]
                await redis_client.setex(redis_key, 300, json.dumps(all_ids))

                log.info("smartolt_polled", tenant=str(tenant_id), olt=olt_map.smartolt_olt_id, new=len(new_alarms))

            except Exception as exc:
                log.warning("smartolt_olt_poll_failed", olt=olt_map.smartolt_olt_id, error=str(exc))
