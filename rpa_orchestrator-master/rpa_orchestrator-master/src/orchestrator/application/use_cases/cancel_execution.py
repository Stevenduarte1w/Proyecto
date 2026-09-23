from __future__ import annotations

from uuid import UUID

from orchestrator.application.dtos import ExecutionResponse
from orchestrator.domain.entities import ExecutionStatus
from orchestrator.domain.ports import (
    BotCommandGateway,
    BotPresenceRepository,
    ExecutionRepository,
)

TERMINAL_EXECUTION_STATUSES = {
    ExecutionStatus.SUCCEEDED,
    ExecutionStatus.FAILED,
    ExecutionStatus.CANCELLED,
}


class CancelExecution:
    def __init__(
        self,
        execution_repository: ExecutionRepository,
        command_gateway: BotCommandGateway,
    ) -> None:
        self._executions = execution_repository
        self._commands = command_gateway

    async def execute(self, execution_id: UUID) -> ExecutionResponse | None:
        execution = await self._executions.get(execution_id)
        if execution is None:
            return None
        if execution.status in TERMINAL_EXECUTION_STATUSES:
            return ExecutionResponse.model_validate(execution)
        if execution.status is ExecutionStatus.CANCELLING:
            return ExecutionResponse.model_validate(execution)
        if execution.bot_id is None:
            execution.mark_cancelled()
            saved = await self._executions.save(execution)
            return ExecutionResponse.model_validate(saved)

        execution.mark_cancelling()
        saved = await self._executions.save(execution)
        await self._commands.send_cancel(execution.bot_id, execution.id)
        return ExecutionResponse.model_validate(saved)


class CompleteExecutionCancellation:
    def __init__(
        self,
        execution_repository: ExecutionRepository,
        presence_repository: BotPresenceRepository,
    ) -> None:
        self._executions = execution_repository
        self._presence = presence_repository

    async def execute(self, execution_id: UUID, actor_bot_id: UUID) -> ExecutionResponse:
        execution = await self._executions.get(execution_id)
        if execution is None:
            raise LookupError("Execution not found")
        if execution.bot_id != actor_bot_id:
            raise PermissionError("Execution is assigned to a different bot")
        if execution.status is ExecutionStatus.CANCELLED:
            await self._presence.release_slot(actor_bot_id, execution_id)
            return ExecutionResponse.model_validate(execution)
        if execution.status is not ExecutionStatus.CANCELLING:
            raise ValueError(
                f"Cannot confirm cancellation from status {execution.status.value}"
            )
        execution.mark_cancelled()
        execution = await self._executions.save(execution)
        await self._presence.release_slot(actor_bot_id, execution_id)
        return ExecutionResponse.model_validate(execution)
