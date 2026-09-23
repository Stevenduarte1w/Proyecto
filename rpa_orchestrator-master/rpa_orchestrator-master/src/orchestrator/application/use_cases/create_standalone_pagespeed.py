from __future__ import annotations

from uuid import uuid4

from orchestrator.application.dtos import ExecutionResponse, StandalonePageSpeedRequest
from orchestrator.application.use_cases.dispatch_execution import DispatchExecution
from orchestrator.domain.entities import Execution, ExecutionStatus
from orchestrator.domain.pagespeed import PAGESPEED_CAPABILITY
from orchestrator.domain.ports import ExecutionRepository, FlowDocumentRepository


class CreateStandalonePageSpeed:
    def __init__(
        self,
        execution_repository: ExecutionRepository,
        flow_document_repository: FlowDocumentRepository,
        dispatcher: DispatchExecution,
    ) -> None:
        self._execution_repository = execution_repository
        self._flow_document_repository = flow_document_repository
        self._dispatcher = dispatcher

    async def execute(self, request: StandalonePageSpeedRequest) -> ExecutionResponse:
        standalone_id = uuid4()
        execution = Execution(
            flow_id=str(standalone_id),
            requested_capability=PAGESPEED_CAPABILITY,
            status=ExecutionStatus.PENDING,
        )
        input_document_id = await self._flow_document_repository.store_document(
            flow_id=str(standalone_id),
            step_name="pagespeed",
            document_type="standalone_execution_input",
            payload={
                "stage": "pagespeed",
                "page_url": str(request.page_url),
                "strategy": request.payload.get(
                    "strategy",
                    ["mobile", "desktop"],
                ),
                "payload": request.payload,
            },
            execution_id=execution.id,
            correlation_id=request.correlation_id,
        )
        execution.input_document_id = input_document_id
        saved_execution = await self._execution_repository.save(execution)
        return await self._dispatcher.dispatch_if_bot_available(saved_execution.id)
