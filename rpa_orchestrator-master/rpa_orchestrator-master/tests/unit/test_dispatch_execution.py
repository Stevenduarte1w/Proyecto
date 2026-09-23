from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from orchestrator.api.v1.routes.bots import _execution_result_request
from orchestrator.application.dtos import BotResponse, DispatchExecutionRequest
from orchestrator.application.use_cases.dispatch_execution import DispatchExecution
from orchestrator.domain.entities import (
    SEO_WORKFLOW_STEPS,
    Bot,
    Execution,
    ExecutionStatus,
    FlowStep,
    SeoFlowStep,
)
from orchestrator.domain.workflow import SEO_MAIN_SUPPORTED_STAGES, SEO_STEP_DEFINITIONS
from orchestrator.infrastructure.bots.ws_manager import BotWebSocketManager


class InMemoryExecutionRepository:
    def __init__(self, execution: Execution | list[Execution]) -> None:
        executions = execution if isinstance(execution, list) else [execution]
        self.executions = {item.id: item for item in executions}
        self.execution = executions[0]

    async def get(self, execution_id: UUID) -> Execution | None:
        return self.executions.get(execution_id)

    async def save(self, execution: Execution) -> Execution:
        self.executions[execution.id] = execution
        self.execution = execution
        return execution

    async def list_dispatchable_for_bot(
        self,
        bot_id: UUID,
        capabilities: list[str],
        limit: int,
    ) -> list[Execution]:
        dispatchable = [
            execution
            for execution in self.executions.values()
            if execution.requested_capability in capabilities
            and (
                (
                    execution.status is ExecutionStatus.PENDING
                    and execution.bot_id in {None, bot_id}
                )
                or (execution.status is ExecutionStatus.QUEUED and execution.bot_id == bot_id)
            )
        ]
        return dispatchable[:limit]


class InMemoryBotRepository:
    def __init__(self, bot: Bot | list[Bot]) -> None:
        self.bots = bot if isinstance(bot, list) else [bot]

    async def list_enabled_by_capability(self, capability: str) -> list[Bot]:
        return [bot for bot in self.bots if capability in bot.capabilities]


class InMemoryFlowStepRepository:
    def __init__(self, step: FlowStep) -> None:
        self.step = step

    async def get(self, step_id: UUID) -> FlowStep | None:
        return self.step if self.step.id == step_id else None

    async def save(self, step: FlowStep) -> FlowStep:
        self.step = step
        return step


class OnlinePresenceRepository:
    async def is_online(self, bot_id: UUID) -> bool:
        return True

    async def reserve_slot(
        self,
        bot_id: UUID,
        execution_id: UUID,
        max_concurrency: int,
    ) -> bool:
        return True

    async def release_slot(self, bot_id: UUID, execution_id: UUID) -> None:
        return None


class InMemoryDocumentRepository:
    def __init__(self, document: dict[str, Any] | dict[str, dict[str, Any]]) -> None:
        self.document = document

    async def get_document(self, document_id: str) -> dict[str, Any] | None:
        if document_id in self.document:
            value = self.document[document_id]
            return value if isinstance(value, dict) else None
        return self.document if document_id == "indexing-input" else None


class RecordingWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


def test_indexing_execution_result_maps_to_success() -> None:
    result = _execution_result_request(
        "execution.result",
        {
            "ok": True,
            "payload": {
                "schema_version": "indexing.result.v1",
                "ok": True,
                "status": "submitted",
            },
        },
    )

    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.error is None


@pytest.mark.parametrize(
    "stage",
    [SeoFlowStep.SEO_AUDIT, SeoFlowStep.WORDPRESS_PUBLISH],
)
async def test_dispatch_sends_supported_stage_to_main_bot(stage: SeoFlowStep) -> None:
    capability = "seo.main"
    bot = Bot(
        name="SEO Main",
        bot_key="seo-main",
        bot_type="seo",
        capabilities=[capability],
    )
    step = FlowStep(
        flow_id=UUID("11111111-1111-1111-1111-111111111111"),
        step_name=stage,
        position=4,
        requested_capability=capability,
    )
    execution = Execution(
        flow_id=str(step.flow_id),
        requested_capability=capability,
        step_id=step.id,
        input_document_id="seo-audit-input",
    )
    websocket = RecordingWebSocket()
    gateway = BotWebSocketManager()
    await gateway.connect(bot.id, "session-1", websocket)  # type: ignore[arg-type]
    audit_payload = {
        "stage": "seo_audit",
        "workflow_stage": "seo_audit",
        "campaign_page_id": 179,
        "queue_execution_id": 299,
        "support_posts": {"mode": "auto"},
    }
    dispatcher = DispatchExecution(
        execution_repository=InMemoryExecutionRepository(execution),
        bot_repository=InMemoryBotRepository(bot),  # type: ignore[arg-type]
        flow_step_repository=InMemoryFlowStepRepository(step),  # type: ignore[arg-type]
        presence_repository=OnlinePresenceRepository(),  # type: ignore[arg-type]
        command_gateway=gateway,
        flow_document_repository=InMemoryDocumentRepository(
            {
                "seo-audit-input": {
                    "payload": audit_payload,
                }
            }
        ),  # type: ignore[arg-type]
    )

    result = await dispatcher.dispatch_if_bot_available(execution.id)

    assert result.status is ExecutionStatus.QUEUED
    expected_message = {
        "type": "execution.run",
        "execution_id": str(execution.id),
        "flow_id": str(step.flow_id),
        "capability": capability,
        "stage": stage.value,
        "input_document_id": "seo-audit-input",
        "input_url": f"/api/v1/executions/{execution.id}/input",
        "result_url": f"/api/v1/executions/{execution.id}/result",
    }
    if stage is SeoFlowStep.SEO_AUDIT:
        expected_message["payload"] = audit_payload
    assert websocket.messages == [expected_message]


async def test_manual_dispatch_can_target_specific_online_bot() -> None:
    capability = "seo.main"
    first_bot = Bot(
        name="SEO Main 1",
        bot_key="seo-main-1",
        bot_type="seo",
        capabilities=[capability],
    )
    second_bot = Bot(
        name="SEO Main 2",
        bot_key="seo-main-2",
        bot_type="seo",
        capabilities=[capability],
    )
    step = FlowStep(
        flow_id=UUID("11111111-1111-1111-1111-111111111111"),
        step_name=SeoFlowStep.WORDPRESS_PUBLISH,
        position=4,
        requested_capability=capability,
    )
    execution = Execution(
        flow_id=str(step.flow_id),
        requested_capability=capability,
        step_id=step.id,
        input_document_id="wordpress-input",
    )
    first_websocket = RecordingWebSocket()
    second_websocket = RecordingWebSocket()
    gateway = BotWebSocketManager()
    await gateway.connect(first_bot.id, "session-1", first_websocket)  # type: ignore[arg-type]
    await gateway.connect(second_bot.id, "session-2", second_websocket)  # type: ignore[arg-type]
    execution_repository = InMemoryExecutionRepository(execution)
    dispatcher = DispatchExecution(
        execution_repository=execution_repository,
        bot_repository=InMemoryBotRepository([first_bot, second_bot]),  # type: ignore[arg-type]
        flow_step_repository=InMemoryFlowStepRepository(step),  # type: ignore[arg-type]
        presence_repository=OnlinePresenceRepository(),  # type: ignore[arg-type]
        command_gateway=gateway,
    )

    result = await dispatcher.execute(
        DispatchExecutionRequest(
            execution_id=execution.id,
            preferred_bot_id=second_bot.id,
        )
    )

    assert result.status is ExecutionStatus.QUEUED
    assert result.bot_id == second_bot.id
    assert execution_repository.execution.bot_id == second_bot.id
    assert first_websocket.messages == []
    assert second_websocket.messages[0]["stage"] == "wordpress_publish"


def test_default_workflow_only_assigns_supported_stages_to_main_bot() -> None:
    main_stages = {
        stage
        for stage in SEO_WORKFLOW_STEPS
        if SEO_STEP_DEFINITIONS[stage].default_capability == "seo.main"
    }

    assert SEO_WORKFLOW_STEPS == (
        SeoFlowStep.WORDPRESS_PAGE_SETUP,
        SeoFlowStep.SEO_AUDIT,
        SeoFlowStep.SUPPORT_POSTS,
        SeoFlowStep.VIDEO_REQUEST,
        SeoFlowStep.WORDPRESS_PUBLISH,
        SeoFlowStep.PAGESPEED,
        SeoFlowStep.INDEXING,
    )
    assert main_stages == SEO_MAIN_SUPPORTED_STAGES
    assert SEO_STEP_DEFINITIONS[SeoFlowStep.SUPPORT_POSTS].depends_on == (
        SeoFlowStep.SEO_AUDIT,
    )
    assert SEO_STEP_DEFINITIONS[SeoFlowStep.VIDEO_REQUEST].depends_on == (
        SeoFlowStep.SEO_AUDIT,
    )
    assert SEO_STEP_DEFINITIONS[SeoFlowStep.WORDPRESS_PUBLISH].depends_on == (
        SeoFlowStep.SEO_AUDIT,
        SeoFlowStep.SUPPORT_POSTS,
        SeoFlowStep.VIDEO_REQUEST,
    )
    assert SEO_STEP_DEFINITIONS[SeoFlowStep.PAGESPEED].depends_on == (
        SeoFlowStep.WORDPRESS_PUBLISH,
    )
    assert SEO_STEP_DEFINITIONS[SeoFlowStep.INDEXING].default_capability == (
        "indexing.submit"
    )
    assert SEO_STEP_DEFINITIONS[SeoFlowStep.INDEXING].depends_on == (
        SeoFlowStep.PAGESPEED,
    )


async def test_dispatch_rejects_unsupported_stage_for_main_bot() -> None:
    capability = "seo.main"
    bot = Bot(
        name="SEO Main",
        bot_key="seo-main",
        bot_type="seo",
        capabilities=[capability],
    )
    step = FlowStep(
        flow_id=UUID("11111111-1111-1111-1111-111111111111"),
        step_name=SeoFlowStep.CONTEXT_BUILDING,
        position=1,
        requested_capability=capability,
    )
    execution = Execution(
        flow_id=str(step.flow_id),
        requested_capability=capability,
        step_id=step.id,
    )
    websocket = RecordingWebSocket()
    gateway = BotWebSocketManager()
    await gateway.connect(bot.id, "session-1", websocket)  # type: ignore[arg-type]
    dispatcher = DispatchExecution(
        execution_repository=InMemoryExecutionRepository(execution),
        bot_repository=InMemoryBotRepository(bot),  # type: ignore[arg-type]
        flow_step_repository=InMemoryFlowStepRepository(step),  # type: ignore[arg-type]
        presence_repository=OnlinePresenceRepository(),  # type: ignore[arg-type]
        command_gateway=gateway,
    )

    result = await dispatcher.dispatch_if_bot_available(execution.id)

    assert result.status is ExecutionStatus.FAILED
    assert result.error_message == "Unsupported stage for seo.main: context_building"
    assert websocket.messages == []


async def test_standalone_pagespeed_dispatches_explicit_stage() -> None:
    capability = "pagespeed.check"
    bot = Bot(
        name="PageSpeed",
        bot_key="pagespeed",
        bot_type="pagespeed",
        capabilities=[capability],
    )
    execution = Execution(
        flow_id="standalone-pagespeed",
        requested_capability=capability,
        input_document_id="pagespeed-input",
    )
    unused_step = FlowStep(
        flow_id=UUID("11111111-1111-1111-1111-111111111111"),
        step_name=SeoFlowStep.PAGESPEED,
        position=1,
        requested_capability=capability,
    )
    websocket = RecordingWebSocket()
    gateway = BotWebSocketManager()
    await gateway.connect(bot.id, "session-1", websocket)  # type: ignore[arg-type]
    dispatcher = DispatchExecution(
        execution_repository=InMemoryExecutionRepository(execution),
        bot_repository=InMemoryBotRepository(bot),  # type: ignore[arg-type]
        flow_step_repository=InMemoryFlowStepRepository(unused_step),  # type: ignore[arg-type]
        presence_repository=OnlinePresenceRepository(),  # type: ignore[arg-type]
        command_gateway=gateway,
    )

    result = await dispatcher.dispatch_if_bot_available(execution.id)

    assert result.status is ExecutionStatus.QUEUED
    assert websocket.messages[0]["capability"] == "pagespeed.check"
    assert websocket.messages[0]["stage"] == "pagespeed"


async def test_indexing_dispatches_execution_start_with_inline_payload() -> None:
    capability = "indexing.submit"
    bot = Bot(
        name="Indexing",
        bot_key="indexing",
        bot_type=capability,
        capabilities=[capability],
    )
    step = FlowStep(
        flow_id=UUID("11111111-1111-1111-1111-111111111111"),
        step_name=SeoFlowStep.INDEXING,
        position=6,
        requested_capability=capability,
    )
    execution = Execution(
        flow_id=str(step.flow_id),
        requested_capability=capability,
        step_id=step.id,
        input_document_id="indexing-input",
    )
    indexing_payload = {
        "schema_version": "indexing.submit.input.v1",
        "page_url": "https://example.com/page/",
        "urls_to_index": [
            "https://example.com/page/",
            "https://example.com/post-1/",
            "https://example.com/post-2/",
        ],
        "providers": {
            "google_search_console": True,
            "twoindex_ninja": True,
        },
    }
    websocket = RecordingWebSocket()
    gateway = BotWebSocketManager()
    await gateway.connect(bot.id, "session-1", websocket)  # type: ignore[arg-type]
    dispatcher = DispatchExecution(
        execution_repository=InMemoryExecutionRepository(execution),
        bot_repository=InMemoryBotRepository(bot),  # type: ignore[arg-type]
        flow_step_repository=InMemoryFlowStepRepository(step),  # type: ignore[arg-type]
        presence_repository=OnlinePresenceRepository(),  # type: ignore[arg-type]
        command_gateway=gateway,
        flow_document_repository=InMemoryDocumentRepository(
            {
                "payload": {
                    "campaign_page_id": 70923,
                    "payload": indexing_payload,
                }
            }
        ),  # type: ignore[arg-type]
    )

    result = await dispatcher.dispatch_if_bot_available(execution.id)

    assert result.status is ExecutionStatus.QUEUED
    assert websocket.messages == [
        {
            "type": "execution.start",
            "bot_type": "indexing.submit",
            "stage": "indexing_submit",
            "flow_id": str(step.flow_id),
            "execution_id": str(execution.id),
            "campaign_page_id": 70923,
            "payload": indexing_payload,
        }
    ]


async def test_detached_indexing_dispatch_uses_indexing_stage() -> None:
    capability = "indexing.submit"
    bot = Bot(
        name="Indexing",
        bot_key="indexing",
        bot_type=capability,
        capabilities=[capability],
    )
    execution = Execution(
        flow_id="11111111-1111-1111-1111-111111111111",
        requested_capability=capability,
        input_document_id="indexing-input",
    )
    unused_step = FlowStep(
        flow_id=UUID(execution.flow_id),
        step_name=SeoFlowStep.INDEXING,
        position=6,
        requested_capability=capability,
    )
    indexing_payload = {
        "schema_version": "indexing.submit.input.v1",
        "page_url": "https://example.com/page/",
        "urls_to_index": ["https://example.com/post-1/"],
        "providers": {
            "google_search_console": True,
            "twoindex_ninja": True,
        },
    }
    websocket = RecordingWebSocket()
    gateway = BotWebSocketManager()
    await gateway.connect(bot.id, "session-1", websocket)  # type: ignore[arg-type]
    dispatcher = DispatchExecution(
        execution_repository=InMemoryExecutionRepository(execution),
        bot_repository=InMemoryBotRepository(bot),  # type: ignore[arg-type]
        flow_step_repository=InMemoryFlowStepRepository(unused_step),  # type: ignore[arg-type]
        presence_repository=OnlinePresenceRepository(),  # type: ignore[arg-type]
        command_gateway=gateway,
        flow_document_repository=InMemoryDocumentRepository(
            {
                "payload": {
                    "campaign_page_id": 70923,
                    "payload": indexing_payload,
                }
            }
        ),  # type: ignore[arg-type]
    )

    result = await dispatcher.dispatch_if_bot_available(execution.id)

    assert result.status is ExecutionStatus.QUEUED
    assert websocket.messages[0]["type"] == "execution.start"
    assert websocket.messages[0]["stage"] == "indexing_submit"
    assert websocket.messages[0]["payload"] == indexing_payload


@pytest.mark.parametrize(
    ("initial_status", "assigned_to_bot"),
    [
        (ExecutionStatus.PENDING, False),
        (ExecutionStatus.PENDING, True),
        (ExecutionStatus.QUEUED, True),
    ],
)
async def test_dispatch_waiting_for_bot_sends_recoverable_post_execution(
    initial_status: ExecutionStatus,
    assigned_to_bot: bool,
) -> None:
    capability = "posts.create"
    bot = Bot(
        name="Posts",
        bot_key="posts",
        bot_type="posts",
        capabilities=[capability],
    )
    step = FlowStep(
        flow_id=UUID("11111111-1111-1111-1111-111111111111"),
        step_name=SeoFlowStep.SUPPORT_POSTS,
        position=2,
        requested_capability=capability,
    )
    execution = Execution(
        flow_id=str(step.flow_id),
        requested_capability=capability,
        status=initial_status,
        bot_id=bot.id if assigned_to_bot else None,
        step_id=step.id,
        input_document_id="posts-input",
    )
    websocket = RecordingWebSocket()
    gateway = BotWebSocketManager()
    await gateway.connect(bot.id, "session-1", websocket)  # type: ignore[arg-type]
    dispatcher = DispatchExecution(
        execution_repository=InMemoryExecutionRepository(execution),
        bot_repository=InMemoryBotRepository(bot),  # type: ignore[arg-type]
        flow_step_repository=InMemoryFlowStepRepository(step),  # type: ignore[arg-type]
        presence_repository=OnlinePresenceRepository(),  # type: ignore[arg-type]
        command_gateway=gateway,
    )

    responses = await dispatcher.dispatch_waiting_for_bot(
        BotResponse(
            id=bot.id,
            name=bot.name,
            bot_key=bot.bot_key,
            bot_type=bot.bot_type,
            capabilities=bot.capabilities,
            max_concurrency=bot.max_concurrency,
            metadata=bot.metadata,
            enabled=bot.enabled,
            last_seen_at=bot.last_seen_at,
        ),
        limit=1,
    )

    assert len(responses) == 1
    assert responses[0].status is ExecutionStatus.QUEUED
    assert responses[0].bot_id == bot.id
    assert websocket.messages == [
        {
            "type": "execution.run",
            "execution_id": str(execution.id),
            "flow_id": str(step.flow_id),
            "capability": capability,
            "stage": SeoFlowStep.SUPPORT_POSTS.value,
            "input_document_id": "posts-input",
            "input_url": f"/api/v1/executions/{execution.id}/input",
            "result_url": f"/api/v1/executions/{execution.id}/result",
        }
    ]


async def test_registration_does_not_redispatch_declared_active_execution() -> None:
    capability = "emails.maturation"
    bot = Bot(
        name="Mail maturation",
        bot_key="mails-maturation-vm01",
        bot_type="emails",
        capabilities=[capability],
        max_concurrency=2,
    )
    active = Execution(
        flow_id="active",
        requested_capability=capability,
        status=ExecutionStatus.QUEUED,
        bot_id=bot.id,
    )
    pending = Execution(flow_id="pending", requested_capability=capability)
    websocket = RecordingWebSocket()
    gateway = BotWebSocketManager()
    await gateway.connect(bot.id, "session-1", websocket)  # type: ignore[arg-type]
    dispatcher = DispatchExecution(
        execution_repository=InMemoryExecutionRepository([active, pending]),
        bot_repository=InMemoryBotRepository(bot),  # type: ignore[arg-type]
        flow_step_repository=InMemoryFlowStepRepository(
            FlowStep(
                flow_id=UUID("11111111-1111-1111-1111-111111111111"),
                step_name=SeoFlowStep.SUPPORT_POSTS,
                position=1,
            )
        ),  # type: ignore[arg-type]
        presence_repository=OnlinePresenceRepository(),  # type: ignore[arg-type]
        command_gateway=gateway,
    )

    responses = await dispatcher.dispatch_waiting_for_bot(
        BotResponse(
            id=bot.id,
            name=bot.name,
            bot_key=bot.bot_key,
            bot_type=bot.bot_type,
            capabilities=bot.capabilities,
            max_concurrency=bot.max_concurrency,
            metadata=bot.metadata,
            enabled=True,
        ),
        limit=1,
        exclude_execution_ids={active.id},
    )

    assert [response.id for response in responses] == [pending.id]
    assert [message["execution_id"] for message in websocket.messages] == [str(pending.id)]
