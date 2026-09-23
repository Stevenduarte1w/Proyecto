from __future__ import annotations

from uuid import UUID

import structlog

from orchestrator.core.config import get_settings
from orchestrator.infrastructure.bots.http_client import HttpBotClient
from orchestrator.infrastructure.postgres.repositories import (
    SqlAlchemyBotRepository,
    SqlAlchemyExecutionRepository,
)
from orchestrator.infrastructure.postgres.session import SessionLocal
from orchestrator.infrastructure.queue.jobs import arq_redis_settings
from orchestrator.infrastructure.redis.locks import redis_lock

logger = structlog.get_logger()


async def run_execution(ctx: dict, execution_id: str) -> None:
    settings = get_settings()
    async with redis_lock(f"execution:{execution_id}:lock", settings.execution_lock_ttl_seconds) as locked:
        if not locked:
            logger.info("execution_lock_skipped", execution_id=execution_id)
            return

        async with SessionLocal() as session:
            executions = SqlAlchemyExecutionRepository(session)
            bots = SqlAlchemyBotRepository(session)
            execution = await executions.get(UUID(execution_id))
            if execution is None:
                logger.warning("execution_not_found", execution_id=execution_id)
                return

            if execution.bot_id is None:
                execution.mark_failed("Execution has no assigned bot")
                await executions.save(execution)
                return

            bot = await bots.get(execution.bot_id)
            if bot is None:
                execution.mark_failed("Assigned bot was not found")
                await executions.save(execution)
                return

            execution.mark_running()
            await executions.save(execution)

            try:
                await HttpBotClient().start_execution(bot.base_url, execution.flow_id, execution.id)
            except Exception as exc:
                execution.mark_failed(str(exc))
                await executions.save(execution)
                raise

            execution.mark_succeeded()
            await executions.save(execution)


class WorkerSettings:
    functions = [run_execution]
    redis_settings = arq_redis_settings()
    max_jobs = 10
    job_timeout = 900
