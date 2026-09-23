from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from orchestrator.infrastructure.redis.client import get_redis


@asynccontextmanager
async def redis_lock(key: str, ttl_seconds: int) -> AsyncIterator[bool]:
    redis = get_redis()
    owner = str(uuid4())
    acquired = await redis.set(key, owner, nx=True, ex=ttl_seconds)
    try:
        yield bool(acquired)
    finally:
        if acquired:
            await redis.eval(
                """
                if redis.call('GET', KEYS[1]) == ARGV[1] then
                  return redis.call('DEL', KEYS[1])
                end
                return 0
                """,
                1,
                key,
                owner,
            )
