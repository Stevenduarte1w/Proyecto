from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from orchestrator.application.dtos import ExecutionProgressMessage
from orchestrator.domain.entities import ExecutionEvent
from orchestrator.domain.ports import ExecutionEventRepository, ExecutionRepository


class ExecutionProgressError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExecutionProgressReceipt:
    status: str
    expected_sequence: int


class RecordExecutionProgress:
    def __init__(
        self,
        execution_repository: ExecutionRepository,
        event_repository: ExecutionEventRepository,
    ) -> None:
        self._executions = execution_repository
        self._events = event_repository

    async def execute(
        self,
        message: ExecutionProgressMessage,
        actor_bot_id: UUID,
    ) -> ExecutionProgressReceipt:
        execution = await self._executions.get(message.execution_id)
        if execution is None:
            raise ExecutionProgressError("not_found", "Execution not found")
        if execution.bot_id != actor_bot_id:
            raise ExecutionProgressError(
                "forbidden",
                "Execution is assigned to a different bot",
            )
        if message.event_type == "stage.end" and not _has_stage_counts(message.payload):
            raise ExecutionProgressError(
                "invalid_message",
                "stage.end requires integer payload.in and payload.out counts",
            )

        status, expected_sequence = await self._events.append(
            ExecutionEvent(
                event_id=message.event_id,
                execution_id=message.execution_id,
                sequence=message.sequence,
                event_type=message.event_type,
                stage=message.stage,
                summary=message.summary,
                payload=message.payload,
            )
        )
        if status == "stored" and message.event_type == "stage.start" and message.stage:
            execution.set_internal_state(message.stage)
            await self._executions.save(execution)
        return ExecutionProgressReceipt(status=status, expected_sequence=expected_sequence)


def _has_stage_counts(payload: dict[str, object]) -> bool:
    return all(
        isinstance(payload.get(field), int) and not isinstance(payload.get(field), bool)
        for field in ("in", "out")
    )
