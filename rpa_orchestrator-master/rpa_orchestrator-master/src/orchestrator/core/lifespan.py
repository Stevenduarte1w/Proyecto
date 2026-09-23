from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import structlog
from fastapi import FastAPI

from orchestrator.core.config import get_settings
from orchestrator.infrastructure.bots.reconciler import run_bot_reconciliation
from orchestrator.infrastructure.mongo.client import close_mongo, init_mongo
from orchestrator.infrastructure.postgres.session import dispose_engine
from orchestrator.infrastructure.redis.client import close_redis, init_redis
from orchestrator.infrastructure.seo_agent.client import dispose_seo_agent_engine

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    try:
        await init_mongo()
    except Exception as exc:
        if settings.app_env != "local":
            raise
        logger.warning("mongo_initialization_skipped", error=str(exc))
    await init_redis()
    reconciliation_stop = asyncio.Event()
    reconciliation_task = asyncio.create_task(
        run_bot_reconciliation(reconciliation_stop),
        name="bot-connection-reconciliation",
    )
    try:
        yield
    finally:
        reconciliation_stop.set()
        reconciliation_task.cancel()
        with suppress(asyncio.CancelledError):
            await reconciliation_task
    await dispose_seo_agent_engine()
    await close_redis()
    await close_mongo()
    await dispose_engine()
