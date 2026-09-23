from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestrator.api.v1.auth import require_dashboard_or_bot_token
from orchestrator.api.v1.dependencies import create_standalone_instagram_use_case
from orchestrator.api.v1.routes.bots import _execution_result_request
from orchestrator.api.v1.routes.executions import router
from orchestrator.application.dtos import (
    BotResponse,
    ExecutionResponse,
    StandaloneInstagramRequest,
)
from orchestrator.application.use_cases.create_standalone_instagram import (
    CreateStandaloneInstagram,
)
from orchestrator.application.use_cases.dispatch_execution import DispatchExecution
from orchestrator.application.use_cases.execution_documents import (
    GetExecutionInput,
    SubmitExecutionResult,
)
from orchestrator.domain.entities import Bot, Execution, ExecutionStatus
from orchestrator.domain.instagram import INSTAGRAM_MADURACION_CAPABILITY

INSTAGRAM_PAYLOAD = {
    "schema_version": "instagram.maduracion.input.v1",
    "stage": "instagram_maduracion",
    "capability": INSTAGRAM_MADURACION_CAPABILITY,
    "task_types": [1, 4, 7],
    "targets": {
        "mode": "accounts",
        "account_ids": [12, 45, 78],
        "owner_id": None,
    },
    "custom_task": {
        "type": "muro",
        "post": "texto del post",
        "links_image": ["https://example.com/image.jpg"],
    },
    "schedule": {"start_date": "2026-09-18T14:00:00Z"},
    "options": {"bot_executor": None, "max_accounts": 50},
}


class InMemoryExecutionRepository:
    def __init__(self, executions: list[Execution] | None = None) -> None:
        self.executions = {item.id: item for item in executions or []}

    async def save(self, execution: Execution) -> Execution:
        self.executions[execution.id] = execution
        return execution

    async def get(self, execution_id: UUID) -> Execution | None:
        return self.executions.get(execution_id)

    async def list_dispatchable_for_bot(
        self,
        bot_id: UUID,
        capabilities: list[str],
        limit: int,
    ) -> list[Execution]:
        return []

    async def list_pending_for_bot(
        self,
        bot_id: UUID,
        capabilities: list[str],
        limit: int,
    ) -> list[Execution]:
        pending = [
            execution
            for execution in self.executions.values()
            if execution.status is ExecutionStatus.PENDING
            and execution.requested_capability in capabilities
            and execution.bot_id in {None, bot_id}
        ]
        return pending[:limit]


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def store_document(
        self,
        flow_id: str,
        step_name: str,
        document_type: str,
        payload: Any,
        execution_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> str:
        document_id = f"instagram-document-{len(self.documents) + 1}"
        self.documents[document_id] = {
            "flow_id": flow_id,
            "step_name": step_name,
            "document_type": document_type,
            "payload": payload,
            "execution_id": execution_id,
            "correlation_id": correlation_id,
        }
        return document_id

    async def get_document(self, document_id: str) -> dict[str, Any] | None:
        return self.documents.get(document_id)


class PendingDispatcher:
    def __init__(self, repository: InMemoryExecutionRepository) -> None:
        self._repository = repository
        self.execution_id: UUID | None = None

    async def dispatch_if_bot_available(self, execution_id: UUID) -> ExecutionResponse:
        self.execution_id = execution_id
        execution = await self._repository.get(execution_id)
        assert execution is not None
        return ExecutionResponse.model_validate(execution)


class EmptyFlowStepRepository:
    async def get(self, step_id: UUID) -> None:
        return None


class BotRepository:
    def __init__(self, bots: list[Bot]) -> None:
        self._bots = bots

    async def list_enabled_by_capability(self, capability: str) -> list[Bot]:
        return [bot for bot in self._bots if capability in bot.capabilities]


class PresenceRepository:
    def __init__(self, *, online: bool, available_slots: int | None = None) -> None:
        self._online = online
        self._available_slots = available_slots
        self.reservations: set[UUID] = set()

    async def is_online(self, bot_id: UUID) -> bool:
        return self._online

    async def available_slots(self, bot_id: UUID) -> int | None:
        return self._available_slots

    async def reserve_slot(
        self,
        bot_id: UUID,
        execution_id: UUID,
        max_concurrency: int,
    ) -> bool:
        if execution_id in self.reservations:
            return True
        if self._available_slots is None or self._available_slots <= 0:
            return False
        if len(self.reservations) >= max_concurrency:
            return False
        self.reservations.add(execution_id)
        return True

    async def release_slot(self, bot_id: UUID, execution_id: UUID) -> None:
        self.reservations.discard(execution_id)


class RecordingGateway:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_execution(self, **message: Any) -> None:
        self.messages.append(message)


class FailingGateway:
    async def send_execution(self, **message: Any) -> None:
        raise RuntimeError("socket closed")


class FailIfAdvancedWorkflow:
    async def execute(self, flow_id: UUID) -> None:
        raise AssertionError("Standalone Instagram must not advance a workflow")


async def test_creates_standalone_instagram_with_integral_input_document() -> None:
    executions = InMemoryExecutionRepository()
    documents = InMemoryDocumentRepository()
    dispatcher = PendingDispatcher(executions)

    result = await CreateStandaloneInstagram(
        execution_repository=executions,
        flow_document_repository=documents,
        dispatcher=dispatcher,  # type: ignore[arg-type]
    ).execute(StandaloneInstagramRequest.model_validate(INSTAGRAM_PAYLOAD))

    assert result.status is ExecutionStatus.PENDING
    assert result.step_id is None
    assert result.requested_capability == INSTAGRAM_MADURACION_CAPABILITY
    assert UUID(result.flow_id)
    assert dispatcher.execution_id == result.id
    assert result.input_document_id is not None
    stored = documents.documents[result.input_document_id]
    assert stored == {
        "flow_id": result.flow_id,
        "step_name": "instagram",
        "document_type": "standalone_execution_input",
        "payload": INSTAGRAM_PAYLOAD,
        "execution_id": result.id,
        "correlation_id": None,
    }

    input_payload = await GetExecutionInput(executions, documents).execute(result.id)
    assert input_payload == INSTAGRAM_PAYLOAD


async def test_instagram_result_is_persisted_without_advancing_workflow() -> None:
    execution = Execution(
        flow_id="11111111-1111-1111-1111-111111111111",
        requested_capability=INSTAGRAM_MADURACION_CAPABILITY,
        status=ExecutionStatus.RUNNING,
    )
    executions = InMemoryExecutionRepository([execution])
    documents = InMemoryDocumentRepository()
    result_payload = {
        "schema_version": "instagram.maduracion.result.v1",
        "ok": True,
        "stage": "instagram_maduracion",
        "totals": {"created": 12, "ok": 11, "error": 1},
        "tasks": [
            {
                "task_bot_id": 8821,
                "account_id": 45,
                "status": "OK",
                "bot_executor": "Bot_Instagram_DESKTOP-MG4482N",
                "end_date": "2026-09-18T15:04:11Z",
                "comment": {},
            }
        ],
    }

    completion = await SubmitExecutionResult(
        execution_repository=executions,
        flow_step_repository=EmptyFlowStepRepository(),  # type: ignore[arg-type]
        flow_document_repository=documents,
        workflow_engine=FailIfAdvancedWorkflow(),  # type: ignore[arg-type]
    ).execute(
        execution.id,
        _execution_result_request(
            "execution.succeeded",
            {"payload": result_payload},
        ),
    )

    assert completion is not None
    assert completion.execution.status is ExecutionStatus.SUCCEEDED
    assert completion.workflow is None
    assert completion.execution.output_document_id is not None
    output = documents.documents[completion.execution.output_document_id]
    assert output["payload"] == result_payload
    assert output["step_name"] == "execution_result"


async def test_dispatch_without_online_instagram_bot_stays_pending() -> None:
    execution = Execution(
        flow_id="standalone-instagram",
        requested_capability=INSTAGRAM_MADURACION_CAPABILITY,
    )
    executions = InMemoryExecutionRepository([execution])
    gateway = RecordingGateway()
    dispatcher = DispatchExecution(
        execution_repository=executions,
        bot_repository=BotRepository([]),  # type: ignore[arg-type]
        flow_step_repository=EmptyFlowStepRepository(),  # type: ignore[arg-type]
        presence_repository=PresenceRepository(online=False),  # type: ignore[arg-type]
        command_gateway=gateway,  # type: ignore[arg-type]
    )

    result = await dispatcher.dispatch_if_bot_available(execution.id)

    assert result.status is ExecutionStatus.PENDING
    assert result.error_message is None
    assert gateway.messages == []


async def test_instagram_bot_with_zero_available_slots_does_not_dispatch() -> None:
    bot = Bot(
        name="Instagram Backend",
        bot_key="instagram-backend-01",
        bot_type="instagram",
        capabilities=[INSTAGRAM_MADURACION_CAPABILITY],
        max_concurrency=10,
    )
    execution = Execution(
        flow_id="standalone-instagram",
        requested_capability=INSTAGRAM_MADURACION_CAPABILITY,
    )
    executions = InMemoryExecutionRepository([execution])
    gateway = RecordingGateway()
    dispatcher = DispatchExecution(
        execution_repository=executions,
        bot_repository=BotRepository([bot]),  # type: ignore[arg-type]
        flow_step_repository=EmptyFlowStepRepository(),  # type: ignore[arg-type]
        presence_repository=PresenceRepository(online=True, available_slots=0),  # type: ignore[arg-type]
        command_gateway=gateway,  # type: ignore[arg-type]
    )

    result = await dispatcher.dispatch_if_bot_available(execution.id)

    assert result.status is ExecutionStatus.PENDING
    assert result.bot_id is None
    assert gateway.messages == []


async def test_positive_heartbeat_capacity_dispatches_only_pending_execution() -> None:
    bot = Bot(
        name="Instagram Backend",
        bot_key="instagram-backend-01",
        bot_type="instagram",
        capabilities=[INSTAGRAM_MADURACION_CAPABILITY],
        max_concurrency=10,
    )
    pending_execution = Execution(
        flow_id="pending-instagram",
        requested_capability=INSTAGRAM_MADURACION_CAPABILITY,
    )
    already_queued_execution = Execution(
        flow_id="queued-instagram",
        requested_capability=INSTAGRAM_MADURACION_CAPABILITY,
        status=ExecutionStatus.QUEUED,
        bot_id=bot.id,
    )
    executions = InMemoryExecutionRepository(
        [pending_execution, already_queued_execution]
    )
    gateway = RecordingGateway()
    dispatcher = DispatchExecution(
        execution_repository=executions,
        bot_repository=BotRepository([bot]),  # type: ignore[arg-type]
        flow_step_repository=EmptyFlowStepRepository(),  # type: ignore[arg-type]
        presence_repository=PresenceRepository(online=True, available_slots=1),  # type: ignore[arg-type]
        command_gateway=gateway,  # type: ignore[arg-type]
    )
    bot_response = BotResponse(
        id=bot.id,
        name=bot.name,
        bot_key=bot.bot_key,
        bot_type=bot.bot_type,
        capabilities=bot.capabilities,
        max_concurrency=bot.max_concurrency,
        metadata=bot.metadata,
        enabled=bot.enabled,
    )

    responses = await dispatcher.dispatch_pending_for_bot(bot_response, limit=1)

    assert [response.id for response in responses] == [pending_execution.id]
    assert pending_execution.status is ExecutionStatus.QUEUED
    assert already_queued_execution.status is ExecutionStatus.QUEUED
    assert [message["execution_id"] for message in gateway.messages] == [
        pending_execution.id
    ]


async def test_declared_slot_policy_applies_to_non_instagram_bot() -> None:
    capability = "emails.maturation"
    bot = Bot(
        name="Mail maturation",
        bot_key="mails-maturation-vm01",
        bot_type="emails",
        capabilities=[capability],
        metadata={"dispatch_policy": "available_slots"},
    )
    execution = Execution(flow_id="standalone-email", requested_capability=capability)
    presence = PresenceRepository(online=True, available_slots=0)
    gateway = RecordingGateway()
    dispatcher = DispatchExecution(
        execution_repository=InMemoryExecutionRepository([execution]),
        bot_repository=BotRepository([bot]),  # type: ignore[arg-type]
        flow_step_repository=EmptyFlowStepRepository(),  # type: ignore[arg-type]
        presence_repository=presence,  # type: ignore[arg-type]
        command_gateway=gateway,  # type: ignore[arg-type]
    )

    result = await dispatcher.dispatch_if_bot_available(execution.id)

    assert result.status is ExecutionStatus.PENDING
    assert gateway.messages == []


async def test_failed_websocket_send_releases_slot_and_returns_pending() -> None:
    capability = "emails.maturation"
    bot = Bot(
        name="Mail maturation",
        bot_key="mails-maturation-vm01",
        bot_type="emails",
        capabilities=[capability],
        metadata={"dispatch_policy": "available_slots"},
    )
    execution = Execution(flow_id="standalone-email", requested_capability=capability)
    executions = InMemoryExecutionRepository([execution])
    presence = PresenceRepository(online=True, available_slots=1)
    dispatcher = DispatchExecution(
        execution_repository=executions,
        bot_repository=BotRepository([bot]),  # type: ignore[arg-type]
        flow_step_repository=EmptyFlowStepRepository(),  # type: ignore[arg-type]
        presence_repository=presence,  # type: ignore[arg-type]
        command_gateway=FailingGateway(),  # type: ignore[arg-type]
    )

    result = await dispatcher.dispatch_if_bot_available(execution.id)

    assert result.status is ExecutionStatus.PENDING
    assert result.bot_id is None
    assert execution.id not in presence.reservations


def test_accounts_mode_without_account_ids_returns_422() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/executions")
    app.dependency_overrides[create_standalone_instagram_use_case] = lambda: object()
    app.dependency_overrides[require_dashboard_or_bot_token] = lambda: None
    invalid_payload = {
        **INSTAGRAM_PAYLOAD,
        "targets": {"mode": "accounts", "owner_id": None},
    }

    with TestClient(app) as client:
        response = client.post("/api/v1/executions/standalone/instagram", json=invalid_payload)

    assert response.status_code == 422
