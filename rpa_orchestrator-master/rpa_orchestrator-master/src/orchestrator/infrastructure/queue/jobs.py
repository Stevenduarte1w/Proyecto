from __future__ import annotations

from uuid import UUID
from urllib.parse import urlparse

from arq import create_pool
from arq.connections import RedisSettings

from orchestrator.core.config import get_settings


def arq_redis_settings() -> RedisSettings:
    parsed = urlparse(get_settings().redis_dsn)
    database = int(parsed.path.lstrip("/") or "0")
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=database,
        password=parsed.password,
    )


class RedisJobQueue:
    async def enqueue_execution(self, execution_id: UUID) -> None:
        redis = await create_pool(arq_redis_settings())
        try:
            await redis.enqueue_job("run_execution", str(execution_id))
        finally:
            await redis.aclose()
