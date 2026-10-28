# ============================================================
# OPSYN CORE INFRASTRUCTURE FILES
# Redis client · Event bus · All middleware
# ============================================================

# ══ app/core/redis_client.py ══════════════════════════════════
# This file: redis_client.py

import redis.asyncio as aioredis
from app.core.config import settings


class RedisPool:
    """Async Redis connection pool singleton."""
    def __init__(self):
        self.client: aioredis.Redis | None = None

    async def connect(self):
        self.client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )

    async def disconnect(self):
        if self.client:
            await self.client.aclose()

    async def ping(self) -> bool:
        try:
            return await self.client.ping()
        except Exception:
            return False


redis_pool = RedisPool()
