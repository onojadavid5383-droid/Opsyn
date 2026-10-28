# ============================================================
# OPSYN INFRASTRUCTURE SYNC — app/tasks/infrastructure_sync.py
# Celery task: poll SmartOLT every 15 min for port data and
# UPSERT into infra_ports (used_capacity, total_capacity, status)
# ============================================================

import asyncio
import logging
from datetime import datetime as _dt, timezone as _tz

import httpx
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.smartolt.models import SmartOLTConfig, SmartOLTOltMap
from app.modules.infrastructure.models import InfrastructureNode, InfraPort

logger = logging.getLogger(__name__)


@shared_task(name="infrastructure.sync_smartolt_ports", bind=True, max_retries=2)
def sync_smartolt_ports(self):
    try:
        asyncio.run(_sync_all())
    except Exception as exc:
        logger.exception("Infrastructure port sync failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)


async def _sync_all() -> None:
    from app.tasks._db import make_task_session

    engine, db = await make_task_session()
    try:
        configs = (await db.execute(
            select(SmartOLTConfig).where(SmartOLTConfig.polling_enabled.is_(True))
        )).scalars().all()

        for cfg in configs:
            try:
                await _sync_tenant(db, cfg)
            except Exception as exc:
                logger.error("Port sync failed for tenant %s: %s", cfg.tenant_id, exc)

        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
        await engine.dispose()


async def _sync_tenant(db, cfg: SmartOLTConfig) -> None:
    headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}

    olt_maps = (await db.execute(
        select(SmartOLTOltMap).where(
            SmartOLTOltMap.tenant_id == cfg.tenant_id,
            SmartOLTOltMap.is_active.is_(True),
        )
    )).scalars().all()

    async with httpx.AsyncClient(timeout=30) as client:
        for olt_map in olt_maps:
            try:
                resp = await client.get(
                    f"{cfg.api_url}/api/v1/olts/{olt_map.smartolt_olt_id}/ports",
                    headers=headers,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "SmartOLT ports returned %d for OLT %s",
                        resp.status_code, olt_map.smartolt_olt_id,
                    )
                    continue
                ports_data = resp.json()
                await _upsert_ports(db, cfg.tenant_id, olt_map, ports_data)
            except Exception as exc:
                logger.warning("Failed syncing ports for OLT %s: %s", olt_map.smartolt_olt_id, exc)


async def _upsert_ports(db, tenant_id, olt_map: SmartOLTOltMap, ports_data: list) -> None:
    # Find infrastructure node matching this OLT (by olt_name / ip)
    node_result = await db.execute(
        select(InfrastructureNode).where(
            InfrastructureNode.tenant_id == tenant_id,
            InfrastructureNode.node_type == "OLT",
        )
    )
    nodes = node_result.scalars().all()
    # Match by olt_name contained in node name
    node = None
    if olt_map.olt_name:
        for n in nodes:
            if olt_map.olt_name.lower() in n.name.lower():
                node = n
                break
    if not node and nodes:
        node = nodes[0]
    if not node:
        return

    now = _dt.now(_tz.utc)
    for port_entry in (ports_data if isinstance(ports_data, list) else ports_data.get("ports", [])):
        port_number    = str(port_entry.get("port_id") or port_entry.get("port_number") or "0")
        total_capacity = int(port_entry.get("total_onus") or port_entry.get("total_capacity") or 128)
        used_capacity  = int(port_entry.get("active_onus") or port_entry.get("used_capacity") or 0)
        port_type      = port_entry.get("port_type", "GPON")
        port_status    = "active" if port_entry.get("operational_state", "up") == "up" else "down"

        stmt = pg_insert(InfraPort).values(
            tenant_id=tenant_id,
            node_id=node.id,
            port_number=port_number,
            port_type=port_type,
            total_capacity=total_capacity,
            used_capacity=used_capacity,
            status=port_status,
            last_synced_at=now,
        ).on_conflict_do_update(
            constraint="uq_infra_port_node_number",
            set_={
                "total_capacity": total_capacity,
                "used_capacity":  used_capacity,
                "status":         port_status,
                "last_synced_at": now,
                "updated_at":     now,
            },
        )
        await db.execute(stmt)
