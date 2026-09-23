from __future__ import annotations

from uuid import uuid4

from orchestrator.application.dtos import ExecutionResponse, StandaloneInstagramRequest
from orchestrator.application.use_cases.dispatch_execution import DispatchExecution
from orchestrator.domain.entities import Execution, ExecutionStatus
from orchestrator.domain.ports import ExecutionRepository, FlowDocumentRepository


class CreateStandaloneInstagram:
    def __init__(
        self,
        execution_repository: ExecutionRepository,
        flow_document_repository: FlowDocumentRepository,
        dispatcher: DispatchExecution,
    ) -> None:
        self._execution_repository = execution_repository
        self._flow_document_repository = flow_document_repository
        self._dispatcher = dispatcher

    async def execute(self, request: StandaloneInstagramRequest) -> ExecutionResponse:
        standalone_id = uuid4()
        execution = Execution(
            flow_id=str(standalone_id),
            requested_capability=request.capability,
            status=ExecutionStatus.PENDING,
        )
        input_document_id = await self._flow_document_repository.store_document(
            flow_id=str(standalone_id),
            step_name="instagram",
            document_type="standalone_execution_input",
            payload=request.model_dump(mode="json", exclude_unset=True),
            execution_id=execution.id,
        )
        execution.input_document_id = input_document_id
        saved_execution = await self._execution_repository.save(execution)
        return await self._dispatcher.dispatch_if_bot_available(saved_execution.id)
