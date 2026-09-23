from __future__ import annotations

import asyncio

import structlog

from orchestrator.application.use_cases.reconcile_bot_connections import (
    ReconcileBotConnections,
)
from orchestrator.core.config import get_settings
from orchestrator.infrastructure.postgres.repositories import SqlAlchemyExecutionRepository
from orchestrator.infrastructure.postgres.session import SessionLocal
from orchestrator.infrastructure.redis.presence import RedisBotPresenceRepository

logger = structlog.get_logger(__name__)


async def run_bot_reconciliation(stop_event: asyncio.Event) -> None:
    interval = get_settings().bot_reconciliation_interval_seconds
    while not stop_event.is_set():
        try:
            async with SessionLocal() as session:
                reconciler = ReconcileBotConnections(
                    SqlAlchemyExecutionRepository(session),
                    RedisBotPresenceRepository(),
                )
                await reconciler.reconcile_expired_sessions()
                await reconciler.sweep_orphan_reservations()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("bot_reconciliation_failed", error=str(exc))

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass
