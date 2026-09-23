from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from uuid import UUID

import structlog

from orchestrator.domain.entities import Execution, ExecutionStatus
from orchestrator.domain.ports import BotPresenceRepository, ExecutionRepository
from orchestrator.infrastructure.redis.locks import redis_lock

logger = structlog.get_logger(__name__)
LockFactory = Callable[[str, int], AbstractAsyncContextManager[bool]]
TERMINAL_STATES = {
    ExecutionStatus.SUCCEEDED,
    ExecutionStatus.FAILED,
    ExecutionStatus.CANCELLED,
}


class ReconcileBotConnections:
    def __init__(
        self,
        execution_repository: ExecutionRepository,
        presence_repository: BotPresenceRepository,
        lock_factory: LockFactory = redis_lock,
    ) -> None:
        self._executions = execution_repository
        self._presence = presence_repository
        self._lock_factory = lock_factory

    async def reconcile_registration(
        self,
        bot_id: UUID,
        declared_active: list[UUID] | None,
    ) -> list[UUID]:
        # None means a legacy bot did not negotiate active_executions. Treating it as
        # an empty list would incorrectly fail all of that bot's running work.
        if declared_active is None:
            return []

        declared = set(declared_active)
        active = await self._executions.list_active_for_bot(bot_id)
        active_by_id = {execution.id: execution for execution in active}
        stale: list[UUID] = []

        for execution_id in declared:
            execution = await self._executions.get(execution_id)
            if (
                execution is None
                or execution.bot_id != bot_id
                or execution.status in TERMINAL_STATES
            ):
                stale.append(execution_id)
                continue
            await self._presence.restore_reservation(bot_id, execution_id)

        for execution_id, execution in active_by_id.items():
            if execution_id not in declared:
                await self._resolve_orphan(execution)

        return stale

    async def reconcile_expired_sessions(self) -> None:
        now = datetime.now(UTC).timestamp()
        for member in await self._presence.expired_sessions(now):
            try:
                raw_bot_id, session_id = member.split(":", 1)
                bot_id = UUID(raw_bot_id)
            except (ValueError, TypeError):
                continue
            async with self._lock_factory(f"lock:bot-session:{bot_id}", 30) as acquired:
                if not acquired:
                    continue
                if not await self._presence.claim_expired_session(member, now):
                    continue
                current_session = await self._presence.current_session_id(bot_id)
                if current_session is not None and current_session != session_id:
                    continue
                if not await self._presence.mark_offline(bot_id, session_id):
                    # A newer session won the race between the read above and the
                    # conditional delete. Its executions must remain untouched.
                    continue
                for execution in await self._executions.list_active_for_bot(bot_id):
                    await self._resolve_orphan(execution)

    async def sweep_orphan_reservations(self) -> None:
        for bot_id in await self._presence.bots_with_reservations():
            for execution_id in await self._presence.reserved_execution_ids(bot_id):
                execution = await self._executions.get(execution_id)
                if (
                    execution is None
                    or execution.bot_id != bot_id
                    or execution.status
                    not in {
                        ExecutionStatus.QUEUED,
                        ExecutionStatus.RUNNING,
                        ExecutionStatus.CANCELLING,
                    }
                ):
                    await self._presence.release_slot(bot_id, execution_id)

    async def _resolve_orphan(self, execution: Execution) -> None:
        bot_id = execution.bot_id
        if bot_id is None:
            return
        if execution.status is ExecutionStatus.QUEUED:
            execution.return_to_pending()
        elif execution.status is ExecutionStatus.RUNNING:
            execution.mark_failed("worker_lost")
        elif execution.status is ExecutionStatus.CANCELLING:
            execution.mark_failed("worker_lost_while_cancelling")
        else:
            return
        await self._executions.save(execution)
        await self._presence.release_slot(bot_id, execution.id)
        logger.warning(
            "orphan_bot_execution_resolved",
            bot_id=str(bot_id),
            execution_id=str(execution.id),
            status=execution.status.value,
        )
