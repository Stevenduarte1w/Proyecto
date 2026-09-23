from __future__ import annotations

from orchestrator.infrastructure.redis.client import get_redis


async def allow_request(key: str, limit: int, window_seconds: int) -> bool:
    redis = get_redis()
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, window_seconds)
    return current <= limit

