# ============================================================
# OPSYN GIS ROUTER — app/modules/gis/router.py
#
#   GET /gis/layers                        layer registry + live counts +
#                                          network revision   {success, data}
#   GET /gis/tiles/{group}/{z}/{x}/{y}.mvt vector tile (raw bytes, 204 if empty)
#   GET /gis/bounds                        extent of the live network {success, data}
#
# All three need network.view. MapLibre sends the bearer token on tile
# requests through transformRequest (frontend MapCanvas), so tiles go
# through the same auth + tenant middleware as every other request.
# ============================================================

from __future__ import annotations

import logging
from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.dependencies.permissions import check_permission
from app.modules.gis import tiles
from app.modules.gis.layer_registry import TILE_GROUPS, build_registry
from app.modules.network.lifecycle import LIVE_STATES
from app.modules.staff.models import User

log = logging.getLogger(__name__)
router = APIRouter()

# The shared redis_pool decodes responses to str; tiles are bytes, so they
# get their own small binary client. A cache failure never fails a tile.
_tile_cache: aioredis.Redis | None = None


def _cache() -> aioredis.Redis | None:
    global _tile_cache
    if _tile_cache is None:
        try:
            _tile_cache = aioredis.from_url(settings.REDIS_URL, decode_responses=False, max_connections=10)
        except Exception:  # pragma: no cover - misconfigured URL
            log.warning("tile cache disabled: cannot create Redis client", exc_info=True)
            return None
    return _tile_cache


async def _cache_get(key: str) -> bytes | None:
    client = _cache()
    if client is None:
        return None
    try:
        return await client.get(key)
    except Exception:
        log.debug("tile cache read failed", exc_info=True)
        return None


async def _cache_set(key: str, value: bytes) -> None:
    client = _cache()
    if client is None:
        return
    try:
        await client.set(key, value, ex=tiles.CACHE_TTL_SECONDS)
    except Exception:
        log.debug("tile cache write failed", exc_info=True)


async def network_revision(db: AsyncSession, tenant_id) -> str:
    return (await db.execute(text(tiles.REVISION_SQL), {"tid": tenant_id})).scalar_one()


@router.get("/gis/layers")
async def get_layers(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("network.view")),
):
    rows = (await db.execute(text(tiles.COUNTS_SQL), {"tid": caller.tenant_id, "live": list(LIVE_STATES)})).all()
    asset_counts = {r.key: int(r.n) for r in rows if r.kind == "asset"}
    cable_counts = {r.key: int(r.n) for r in rows if r.kind == "cable"}
    revision = await network_revision(db, caller.tenant_id)
    return {"success": True, "data": build_registry(asset_counts, cable_counts, revision)}


@router.get("/gis/bounds")
async def get_bounds(
    db:     AsyncSession = Depends(get_db),
    caller: User         = Depends(check_permission("network.view")),
):
    r = (await db.execute(text(tiles.BOUNDS_SQL), {"tid": caller.tenant_id, "live": list(LIVE_STATES)})).first()
    bbox = None
    if r is not None and r.min_lng is not None:
        bbox = [float(r.min_lng), float(r.min_lat), float(r.max_lng), float(r.max_lat)]
    return {"success": True, "data": {"bbox": bbox, "feature_count": int(r.n) if r else 0}}


@router.get("/gis/tiles/{group}/{z}/{x}/{y}.mvt")
async def get_tile(
    group:  str,
    z:      int,
    x:      int,
    y:      int,
    rev:    Optional[str] = Query(None, description="Network revision from /gis/layers — enables caching"),
    db:     AsyncSession  = Depends(get_db),
    caller: User          = Depends(check_permission("network.view")),
):
    if group not in TILE_GROUPS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown tile group '{group}'")
    if not tiles.valid_tile(z, x, y):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tile out of range")

    cacheable = tiles.valid_revision(rev)
    key = tiles.cache_key(str(caller.tenant_id), rev, group, z, x, y) if cacheable else None
    headers = {"Cache-Control": "private, max-age=3600" if cacheable else "private, no-cache"}

    data = await _cache_get(key) if key else None
    if data is None:
        data = (await db.execute(text(tiles.TILE_SQL), tiles.tile_params(caller.tenant_id, z, x, y))).scalar_one()
        data = bytes(data or b"")
        if key:
            await _cache_set(key, data)

    if not data:
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers=headers)
    return Response(content=data, media_type=tiles.MVT_MEDIA_TYPE, headers=headers)
