from __future__ import annotations

from typing import Any
from uuid import UUID

from orchestrator.application.dtos import ExecutionResponse, StandalonePageSpeedRequest
from orchestrator.application.use_cases.create_standalone_pagespeed import CreateStandalonePageSpeed
from orchestrator.domain.entities import Execution, ExecutionStatus


class InMemoryExecutionRepository:
    def __init__(self) -> None:
        self.executions: dict[UUID, Execution] = {}

    async def save(self, execution: Execution) -> Execution:
        self.executions[execution.id] = execution
        return execution

    async def get(self, execution_id: UUID) -> Execution | None:
        return self.executions.get(execution_id)


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self.stored: dict[str, Any] | None = None

    async def store_document(
        self,
        flow_id: str,
        step_name: str,
        document_type: str,
        payload: dict[str, Any],
        execution_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> str:
        self.stored = {
            "flow_id": flow_id,
            "step_name": step_name,
            "document_type": document_type,
            "payload": payload,
            "execution_id": execution_id,
            "correlation_id": correlation_id,
        }
        return "pagespeed-input-document"

    async def get_document(self, document_id: str) -> dict[str, Any] | None:
        return self.stored if document_id == "pagespeed-input-document" else None


class PendingDispatcher:
    def __init__(self, repository: InMemoryExecutionRepository) -> None:
        self.repository = repository
        self.dispatched_execution_id: UUID | None = None

    async def dispatch_if_bot_available(self, execution_id: UUID) -> ExecutionResponse:
        self.dispatched_execution_id = execution_id
        execution = await self.repository.get(execution_id)
        assert execution is not None
        return ExecutionResponse.model_validate(execution)


async def test_creates_and_attempts_to_dispatch_standalone_pagespeed() -> None:
    execution_repository = InMemoryExecutionRepository()
    document_repository = InMemoryDocumentRepository()
    dispatcher = PendingDispatcher(execution_repository)
    use_case = CreateStandalonePageSpeed(
        execution_repository=execution_repository,
        flow_document_repository=document_repository,
        dispatcher=dispatcher,  # type: ignore[arg-type]
    )

    result = await use_case.execute(
        StandalonePageSpeedRequest(
            page_url="https://example.com/page",
            payload={"strategy": ["mobile", "desktop"]},
            correlation_id="manual-001",
        )
    )

    assert result.requested_capability == "pagespeed.check"
    assert result.status is ExecutionStatus.PENDING
    assert result.step_id is None
    assert result.input_document_id == "pagespeed-input-document"
    assert dispatcher.dispatched_execution_id == result.id
    assert document_repository.stored == {
        "flow_id": result.flow_id,
        "step_name": "pagespeed",
        "document_type": "standalone_execution_input",
        "payload": {
            "stage": "pagespeed",
            "page_url": "https://example.com/page",
            "strategy": ["mobile", "desktop"],
            "payload": {"strategy": ["mobile", "desktop"]},
        },
        "execution_id": result.id,
        "correlation_id": "manual-001",
    }
