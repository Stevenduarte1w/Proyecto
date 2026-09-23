from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from orchestrator.application.dtos import (
    ExecutionResponse,
    ExecutionResultRequest,
    FlowSubmitRequest,
)
from orchestrator.application.use_cases.advance_workflow import AdvanceWorkflow
from orchestrator.application.use_cases.execution_checkpoint import (
    ProcessExecutionCheckpoint,
)
from orchestrator.application.use_cases.execution_documents import (
    SubmitExecutionResult,
    _seo_audit_validation_error,
    _seo_main_result_validation_error,
)
from orchestrator.application.use_cases.submit_flow import SubmitFlow
from orchestrator.domain.entities import (
    Execution,
    ExecutionCheckpoint,
    ExecutionStatus,
    Flow,
    FlowStatus,
    FlowStep,
    FlowStepStatus,
    SeoFlowStep,
)


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
        document_id = f"document-{len(self.documents) + 1}"
        self.documents[document_id] = {
            "_id": document_id,
            "flow_id": flow_id,
            "step_name": step_name,
            "document_type": document_type,
            "payload": payload,
            "execution_id": str(execution_id) if execution_id else None,
            "correlation_id": correlation_id,
        }
        return document_id

    async def get_document(self, document_id: str) -> dict[str, Any] | None:
        return self.documents.get(document_id)


class InMemoryFlowRepository:
    def __init__(self) -> None:
        self.flows: dict[UUID, Flow] = {}

    async def save(self, flow: Flow) -> Flow:
        self.flows[flow.id] = flow
        return flow

    async def get(self, flow_id: UUID) -> Flow | None:
        return self.flows.get(flow_id)


class InMemoryFlowStepRepository:
    def __init__(self) -> None:
        self.steps: dict[UUID, FlowStep] = {}

    async def save(self, step: FlowStep) -> FlowStep:
        self.steps[step.id] = step
        return step

    async def save_many(self, steps: list[FlowStep]) -> list[FlowStep]:
        self.steps.update({step.id: step for step in steps})
        return steps

    async def get(self, step_id: UUID) -> FlowStep | None:
        return self.steps.get(step_id)

    async def list_by_flow(self, flow_id: UUID) -> list[FlowStep]:
        return sorted(
            (step for step in self.steps.values() if step.flow_id == flow_id),
            key=lambda step: step.position,
        )


class InMemoryExecutionRepository:
    def __init__(self) -> None:
        self.executions: dict[UUID, Execution] = {}

    async def save(self, execution: Execution) -> Execution:
        self.executions[execution.id] = execution
        return execution

    async def get(self, execution_id: UUID) -> Execution | None:
        return self.executions.get(execution_id)


class RecordingPageExecutionService:
    def __init__(self) -> None:
        self.artifacts: list[dict[str, Any]] = []

    async def store_artifact(
        self,
        queue_execution_id: int,
        filename: str,
        payload: Any,
    ) -> dict[str, Any]:
        artifact = {
            "queue_execution_id": queue_execution_id,
            "filename": filename,
            "payload": payload,
        }
        self.artifacts.append(artifact)
        return artifact


class InMemoryExecutionCheckpointRepository:
    def __init__(self) -> None:
        self.checkpoints: dict[tuple[UUID, str], ExecutionCheckpoint] = {}

    async def create(
        self,
        checkpoint: ExecutionCheckpoint,
    ) -> tuple[ExecutionCheckpoint, bool]:
        key = (checkpoint.execution_id, checkpoint.checkpoint)
        existing = self.checkpoints.get(key)
        if existing is not None:
            return existing, False
        self.checkpoints[key] = checkpoint
        return checkpoint, True

    async def save(self, checkpoint: ExecutionCheckpoint) -> ExecutionCheckpoint:
        self.checkpoints[(checkpoint.execution_id, checkpoint.checkpoint)] = checkpoint
        return checkpoint

    async def get(
        self,
        execution_id: UUID,
        checkpoint: str,
    ) -> ExecutionCheckpoint | None:
        return self.checkpoints.get((execution_id, checkpoint))


class RecordingDispatcher:
    def __init__(self, executions: InMemoryExecutionRepository) -> None:
        self._executions = executions
        self.calls: list[dict[str, UUID | None]] = []

    async def dispatch_if_bot_available(
        self,
        execution_id: UUID,
        *,
        preferred_bot_id: UUID | None = None,
    ) -> ExecutionResponse:
        self.calls.append(
            {
                "execution_id": execution_id,
                "preferred_bot_id": preferred_bot_id,
            }
        )
        execution = await self._executions.get(execution_id)
        assert execution is not None
        return ExecutionResponse.model_validate(execution)


@pytest.mark.parametrize(
    ("flow_status", "publish_status", "indexing_status", "expected_status"),
    [
        (FlowStatus.FAILED, FlowStepStatus.SUCCEEDED, FlowStepStatus.FAILED, "success"),
        (FlowStatus.FAILED, FlowStepStatus.FAILED, FlowStepStatus.PENDING, "failed"),
        (FlowStatus.SUCCEEDED, FlowStepStatus.SUCCEEDED, FlowStepStatus.SUCCEEDED, "success"),
    ],
)
async def test_queue_result_tracks_publication_even_when_indexing_fails(
    flow_status: FlowStatus,
    publish_status: FlowStepStatus,
    indexing_status: FlowStepStatus,
    expected_status: str,
) -> None:
    class RecordingSeoManagementRepository:
        def __init__(self) -> None:
            self.updated: dict[str, Any] | None = None

        async def update_queue_result(
            self,
            queue_execution_id: int,
            *,
            status: str,
            result_status: str,
            error_message: str | None = None,
        ) -> None:
            self.updated = {
                "queue_execution_id": queue_execution_id,
                "status": status,
                "result_status": result_status,
                "error_message": error_message,
            }

    flow = Flow(
        flow_type="commercial_page_seo",
        page_url="https://example.com/page",
        correlation_id="seo-agent-queue:1790",
        status=flow_status,
    )
    steps = InMemoryFlowStepRepository()
    await steps.save_many(
        [
            FlowStep(
                flow_id=flow.id,
                step_name=SeoFlowStep.WORDPRESS_PUBLISH,
                position=5,
                status=publish_status,
                error_message=(
                    "Publication failed"
                    if publish_status is FlowStepStatus.FAILED
                    else None
                ),
            ),
            FlowStep(
                flow_id=flow.id,
                step_name=SeoFlowStep.INDEXING,
                position=7,
                status=indexing_status,
                error_message=(
                    "Indexing result requires status=submitted"
                    if indexing_status is FlowStepStatus.FAILED
                    else None
                ),
            ),
        ]
    )
    management = RecordingSeoManagementRepository()
    use_case = SubmitExecutionResult(
        execution_repository=InMemoryExecutionRepository(),
        flow_step_repository=steps,
        flow_document_repository=InMemoryDocumentRepository(),
        workflow_engine=None,  # type: ignore[arg-type]
        seo_management_repository=management,  # type: ignore[arg-type]
    )

    await use_case._sync_source_queue(SimpleNamespace(flow=flow))

    assert management.updated is not None
    assert management.updated["queue_execution_id"] == 1790
    assert management.updated["status"] == expected_status
    if publish_status is FlowStepStatus.SUCCEEDED:
        assert management.updated["result_status"] == "published"
        if indexing_status is FlowStepStatus.FAILED:
            assert "indexing" in management.updated["error_message"]
            assert "manualmente" in management.updated["error_message"]
        else:
            assert management.updated["error_message"] is None
    else:
        assert management.updated["result_status"] == "failed"
        assert "wordpress_publish" in management.updated["error_message"]


def test_flow_request_requires_campaign_page_id() -> None:
    with pytest.raises(ValidationError):
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            page_url="https://example.com/service",
            payload={},
        )


def test_wordpress_page_setup_requires_campaign_id_for_bot_lookup() -> None:
    with pytest.raises(ValidationError):
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            queue_execution_id=42,
            campaign_page_id=321,
            page_url="https://example.com/registered-slug/",
            page_setup={"action": "create", "slug": "registered-slug"},
            payload={},
        )


async def test_wordpress_page_setup_runs_first_and_preserves_registered_slug() -> None:
    documents = InMemoryDocumentRepository()
    flows = InMemoryFlowRepository()
    steps = InMemoryFlowStepRepository()
    executions = InMemoryExecutionRepository()
    submitted = await SubmitFlow(
        flow_document_repository=documents,
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
    ).execute(
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            queue_execution_id=42,
            campaign_page_id=321,
            page_url="https://example.com/url-can-change/",
            requested_capability="seo.main",
            page_setup={
                "action": "create",
                "slug": "registered-slug",
                "campaign_id": 7,
            },
            payload={},
        )
    )

    assert submitted.flow.current_step is SeoFlowStep.WORDPRESS_PAGE_SETUP
    assert submitted.initial_execution.requested_capability == "wordpress.page_upsert"
    setup_input = documents.documents[submitted.initial_execution.input_document_id or ""]
    assert setup_input["payload"]["stage"] == "wordpress_page_setup"
    assert setup_input["payload"]["action"] == "create"
    assert setup_input["payload"]["slug"] == "registered-slug"

    steps_by_name = {step.step_name: step for step in await steps.list_by_flow(submitted.flow.id)}
    assert steps_by_name[SeoFlowStep.WORDPRESS_PAGE_SETUP].status is FlowStepStatus.QUEUED
    assert steps_by_name[SeoFlowStep.SEO_AUDIT].status is FlowStepStatus.PENDING


async def test_wordpress_page_setup_result_stores_wp_id_and_starts_audit() -> None:
    class RecordingSeoManagementRepository:
        def __init__(self) -> None:
            self.updated: tuple[int, int] | None = None

        async def update_page_wp_page_id(
            self,
            campaign_page_id: int,
            wp_page_id: int,
        ) -> None:
            self.updated = (campaign_page_id, wp_page_id)

    documents = InMemoryDocumentRepository()
    flows = InMemoryFlowRepository()
    steps = InMemoryFlowStepRepository()
    executions = InMemoryExecutionRepository()
    submitted = await SubmitFlow(
        flow_document_repository=documents,
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
    ).execute(
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            queue_execution_id=42,
            campaign_page_id=321,
            page_url="https://example.com/registered-slug/",
            requested_capability="seo.main",
            page_setup={
                "action": "create",
                "slug": "registered-slug",
                "campaign_id": 7,
            },
            payload={},
        )
    )
    management = RecordingSeoManagementRepository()
    workflow = AdvanceWorkflow(
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
        flow_document_repository=documents,
    )

    completion = await SubmitExecutionResult(
        execution_repository=executions,
        flow_step_repository=steps,
        flow_document_repository=documents,
        workflow_engine=workflow,
        seo_management_repository=management,  # type: ignore[arg-type]
    ).execute(
        submitted.initial_execution.id,
        ExecutionResultRequest(
            status="succeeded",
            payload={
                "schema_version": "wordpress.page_setup.result.v1",
                "ok": True,
                "action": "create",
                "wp_page_id": 789,
                "slug": "registered-slug",
            },
        ),
    )

    assert completion is not None
    assert management.updated == (321, 789)
    assert completion.workflow is not None
    assert len(completion.workflow.created_executions) == 1
    audit_execution = completion.workflow.created_executions[0]
    assert audit_execution.requested_capability == "seo.main"
    audit_input = documents.documents[audit_execution.input_document_id or ""]["payload"]
    assert audit_input["stage"] == "seo_audit"
    assert audit_input["page_setup_result"]["wp_page_id"] == 789


def test_post_payload_rejects_items_outside_expected_contract() -> None:
    error = _seo_audit_validation_error(
        {
            "post_bot_payload": [
                {
                    "campaign_id": "https://example.com/path",
                    "post_title": "Incomplete post",
                }
            ],
            "video_bot_payload": {},
        }
    )

    assert error is not None
    assert "missing required fields" in error


def test_rewrite_result_requires_non_empty_elementor_data() -> None:
    error = _seo_main_result_validation_error(
        {
            "schema_version": "seo.rewrite.v1",
            "ok": True,
            "stage": "page_rewrite",
            "campaign_page_id": 321,
            "page_update": {"updated_elementor_data": {}},
            "pending_insertions": {},
        }
    )

    assert error == ("SEO rewrite_result requires non-empty page_update.updated_elementor_data")


async def test_seo_main_payloads_include_required_page_identity() -> None:
    documents = InMemoryDocumentRepository()
    flows = InMemoryFlowRepository()
    steps = InMemoryFlowStepRepository()
    executions = InMemoryExecutionRepository()
    submit_flow = SubmitFlow(
        flow_document_repository=documents,
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
    )

    submitted = await submit_flow.execute(
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            queue_execution_id=99,
            campaign_page_id=321,
            page_url="https://example.com/service",
            requested_capability="seo.main",
            payload={},
        )
    )

    phase_one = documents.documents[submitted.flow.initial_document_id or ""]
    assert phase_one["payload"]["stage"] == "seo_audit"
    assert phase_one["payload"]["workflow_stage"] == "seo_audit"
    assert phase_one["payload"]["queue_execution_id"] == 99
    assert phase_one["payload"]["campaign_page_id"] == 321
    assert phase_one["payload"]["page_url"] == "https://example.com/service"
    assert phase_one["payload"]["log_url"] == "/api/v1/page-executions/99/log"
    assert phase_one["payload"]["log_method"] == "PUT"
    assert phase_one["payload"]["artifacts_url"] == ("/api/v1/page-executions/99/artifacts")
    assert phase_one["payload"]["support_posts"] == {"mode": "auto"}
    assert "payload" not in phase_one["payload"]

    flow_steps = await steps.list_by_flow(submitted.flow.id)
    for flow_step in flow_steps:
        if flow_step.step_name in {
            SeoFlowStep.SEO_AUDIT,
            SeoFlowStep.SUPPORT_POSTS,
            SeoFlowStep.VIDEO_REQUEST,
        }:
            result_payload: dict[str, Any] = {}
            if flow_step.step_name is SeoFlowStep.SUPPORT_POSTS:
                result_payload = {"posts": []}
            elif flow_step.step_name is SeoFlowStep.VIDEO_REQUEST:
                result_payload = {"video_url": "https://example.com/video"}
            output_id = await documents.store_document(
                flow_id=str(submitted.flow.id),
                step_name=flow_step.step_name.value,
                document_type="succeeded",
                payload=result_payload,
                execution_id=flow_step.execution_id,
            )
            flow_step.mark_succeeded(output_id)
            await steps.save(flow_step)

    workflow = AdvanceWorkflow(
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
        flow_document_repository=documents,
    )
    advanced = await workflow.execute(submitted.flow.id)

    assert advanced is not None
    phase_two = documents.documents[advanced.created_executions[0].input_document_id or ""]
    assert phase_two["payload"]["stage"] == "wordpress_publish"
    assert phase_two["payload"]["queue_execution_id"] == 99
    assert phase_two["payload"]["campaign_page_id"] == 321
    assert phase_two["payload"]["page_url"] == "https://example.com/service"
    assert phase_two["payload"]["log_url"] == "/api/v1/page-executions/99/log"
    assert phase_two["payload"]["log_method"] == "PUT"
    assert phase_two["payload"]["artifacts_url"] == ("/api/v1/page-executions/99/artifacts")


async def test_seo_audit_payload_sends_only_support_posts_mode() -> None:
    documents = InMemoryDocumentRepository()
    submitted = await SubmitFlow(
        flow_document_repository=documents,
        flow_repository=InMemoryFlowRepository(),
        flow_step_repository=InMemoryFlowStepRepository(),
        execution_repository=InMemoryExecutionRepository(),
    ).execute(
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            queue_execution_id=299,
            campaign_page_id=179,
            page_url="https://example.com/service",
            requested_capability="seo.main",
            payload={
                "support_posts": {"mode": "state_defined"},
                "create_if_missing": True,
                "reuse_if_published": True,
                "sync_wordpress_by_slug": True,
                "post_title": "Do not send",
                "keyphrase": "do not send",
                "slug": "do-not-send",
                "post_category": "Do not send",
                "post_urls": ["https://example.com/post/"],
            },
        )
    )

    phase_one = documents.documents[submitted.flow.initial_document_id or ""]["payload"]

    assert phase_one["support_posts"] == {"mode": "state_defined"}
    forbidden_fields = {
        "create_if_missing",
        "reuse_if_published",
        "sync_wordpress_by_slug",
        "post_title",
        "keyphrase",
        "slug",
        "post_category",
        "post_urls",
        "payload",
    }
    assert forbidden_fields.isdisjoint(phase_one)


async def test_wordpress_publish_prefers_seo_audit_bot_when_dispatching() -> None:
    documents = InMemoryDocumentRepository()
    flows = InMemoryFlowRepository()
    steps = InMemoryFlowStepRepository()
    executions = InMemoryExecutionRepository()
    submitted = await SubmitFlow(
        flow_document_repository=documents,
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
    ).execute(
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            queue_execution_id=99,
            campaign_page_id=321,
            page_url="https://example.com/service",
            requested_capability="seo.main",
            payload={},
        )
    )
    source_bot_id = UUID("65bc05ad-dfbf-4a3e-943a-e2862d4f74f1")
    audit_execution = executions.executions[submitted.initial_execution.id]
    audit_execution.bot_id = source_bot_id
    await executions.save(audit_execution)

    flow_steps = {step.step_name: step for step in await steps.list_by_flow(submitted.flow.id)}
    rewrite_result = {
        "schema_version": "seo.rewrite.v1",
        "ok": True,
        "stage": "page_rewrite",
        "campaign_page_id": 321,
        "page_update": {
            "updated_elementor_data": [{"id": "hero", "settings": {}}],
        },
        "pending_insertions": {"posts": [], "video": None},
    }
    audit_output_id = await documents.store_document(
        flow_id=str(submitted.flow.id),
        step_name=SeoFlowStep.SEO_AUDIT.value,
        document_type="succeeded",
        payload=rewrite_result,
        execution_id=audit_execution.id,
    )
    flow_steps[SeoFlowStep.SEO_AUDIT].mark_succeeded(audit_output_id)
    await steps.save(flow_steps[SeoFlowStep.SEO_AUDIT])

    posts_output_id = await documents.store_document(
        flow_id=str(submitted.flow.id),
        step_name=SeoFlowStep.SUPPORT_POSTS.value,
        document_type="skipped",
        payload={"posts": [], "published_posts": [], "skipped": True},
    )
    flow_steps[SeoFlowStep.SUPPORT_POSTS].mark_skipped(posts_output_id)
    await steps.save(flow_steps[SeoFlowStep.SUPPORT_POSTS])

    video_output_id = await documents.store_document(
        flow_id=str(submitted.flow.id),
        step_name=SeoFlowStep.VIDEO_REQUEST.value,
        document_type="skipped",
        payload={"skipped": True},
    )
    flow_steps[SeoFlowStep.VIDEO_REQUEST].mark_skipped(video_output_id)
    await steps.save(flow_steps[SeoFlowStep.VIDEO_REQUEST])

    dispatcher = RecordingDispatcher(executions)
    advanced = await AdvanceWorkflow(
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
        flow_document_repository=documents,
        dispatcher=dispatcher,  # type: ignore[arg-type]
    ).execute(submitted.flow.id)

    assert advanced is not None
    wordpress_execution = advanced.created_executions[0]
    assert wordpress_execution.requested_capability == "seo.main"
    assert wordpress_execution.bot_id == source_bot_id
    assert dispatcher.calls == [
        {
            "execution_id": wordpress_execution.id,
            "preferred_bot_id": source_bot_id,
        }
    ]


async def test_seo_audit_routes_post_payload_to_posts_bot() -> None:
    documents = InMemoryDocumentRepository()
    flows = InMemoryFlowRepository()
    steps = InMemoryFlowStepRepository()
    executions = InMemoryExecutionRepository()
    submit_flow = SubmitFlow(
        flow_document_repository=documents,
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
    )
    submitted = await submit_flow.execute(
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            queue_execution_id=299,
            campaign_page_id=179,
            page_url="https://example.com/service",
            requested_capability="seo.main",
            payload={},
        )
    )
    workflow = AdvanceWorkflow(
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
        flow_document_repository=documents,
    )
    post_bot_payload = [
        {
            "campaign_id": "https://example.com",
            "post_title": "Mi artículo",
            "image_prompt": "paisaje de montaña al atardecer",
            "seo_title": "Mi artículo SEO",
            "meta_description": "Descubre todo sobre...",
            "content": "<h1>Mi artículo</h1><p>Contenido...</p>",
            "keyphrase": "mi artículo",
            "slug": "mi-articulo",
            "category": "Blog",
            "hashtags": "tag1,tag2",
            "image_alt": "imagen descriptiva",
            "create_category": False,
        }
    ]
    post_bot_payload.append(
        {
            **post_bot_payload[0],
            "post_title": "Segundo artículo",
            "seo_title": "Segundo artículo SEO",
            "slug": "segundo-articulo",
        }
    )
    video_bot_payload = {
        "title": "Video",
        "script": "Script",
        "keywords": ["keyword"],
        "target_page": "https://example.com/service",
    }

    completion = await SubmitExecutionResult(
        execution_repository=executions,
        flow_step_repository=steps,
        flow_document_repository=documents,
        workflow_engine=workflow,
    ).execute(
        submitted.initial_execution.id,
        ExecutionResultRequest(
            status="succeeded",
            payload={
                "post_bot_payload": post_bot_payload,
                "video_bot_payload": video_bot_payload,
            },
        ),
    )

    assert completion is not None
    assert completion.execution.status is ExecutionStatus.SUCCEEDED
    assert completion.workflow is not None
    external_executions = {
        execution.requested_capability: execution
        for execution in completion.workflow.created_executions
    }
    posts_input = documents.documents[external_executions["posts.create"].input_document_id or ""][
        "payload"
    ]
    assert posts_input["stage"] == "support_posts"
    assert posts_input["flow_id"] == str(submitted.flow.id)
    assert posts_input["source_execution_id"] == str(submitted.initial_execution.id)
    assert posts_input["queue_execution_id"] == 299
    assert posts_input["campaign_page_id"] == 179
    assert posts_input["payload"] == post_bot_payload
    assert "dependencies" not in posts_input

    video_input = documents.documents[external_executions["video.create"].input_document_id or ""][
        "payload"
    ]
    assert video_input["stage"] == "video_request"
    assert video_input["payload"] == video_bot_payload


async def test_invalid_seo_audit_does_not_create_posts_execution() -> None:
    documents = InMemoryDocumentRepository()
    flows = InMemoryFlowRepository()
    steps = InMemoryFlowStepRepository()
    executions = InMemoryExecutionRepository()
    submitted = await SubmitFlow(
        flow_document_repository=documents,
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
    ).execute(
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            queue_execution_id=299,
            campaign_page_id=179,
            page_url="https://example.com/service",
            requested_capability="seo.main",
            payload={},
        )
    )
    workflow = AdvanceWorkflow(
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
        flow_document_repository=documents,
    )

    completion = await SubmitExecutionResult(
        execution_repository=executions,
        flow_step_repository=steps,
        flow_document_repository=documents,
        workflow_engine=workflow,
    ).execute(
        submitted.initial_execution.id,
        ExecutionResultRequest(
            status="succeeded",
            payload={
                "video_bot_payload": {},
            },
        ),
    )

    assert completion is not None
    assert completion.execution.status is ExecutionStatus.FAILED
    assert completion.execution.error_message is not None
    assert "post_bot_payload" in completion.execution.error_message
    assert completion.workflow is not None
    assert completion.workflow.created_executions == []


async def test_pagespeed_result_is_copied_to_page_execution_artifacts() -> None:
    documents = InMemoryDocumentRepository()
    flows = InMemoryFlowRepository()
    steps = InMemoryFlowStepRepository()
    executions = InMemoryExecutionRepository()
    flow = Flow(flow_type="commercial_page_seo", page_url="https://example.com/service")
    initial_document_id = await documents.store_document(
        flow_id=str(flow.id),
        step_name="initial_request",
        document_type="flow_input",
        payload={
            "queue_execution_id": 777,
            "campaign_page_id": 179,
            "page_url": "https://example.com/service",
        },
    )
    flow.initial_document_id = initial_document_id
    await flows.save(flow)

    input_document_id = await documents.store_document(
        flow_id=str(flow.id),
        step_name="pagespeed",
        document_type="workflow_step_input",
        payload={
            "stage": "pagespeed",
            "queue_execution_id": 777,
            "campaign_page_id": 179,
            "page_url": "https://example.com/service",
            "strategy": ["mobile", "desktop"],
        },
    )
    pagespeed_step = FlowStep(
        flow_id=flow.id,
        step_name=SeoFlowStep.PAGESPEED,
        position=1,
        input_document_id=input_document_id,
        requested_capability="pagespeed.check",
    )
    indexing_step = FlowStep(
        flow_id=flow.id,
        step_name=SeoFlowStep.INDEXING,
        position=2,
        requested_capability="indexing.submit",
    )
    execution = Execution(
        flow_id=str(flow.id),
        step_id=pagespeed_step.id,
        requested_capability="pagespeed.check",
        input_document_id=input_document_id,
    )
    pagespeed_step.assign_execution(execution.id)
    await steps.save_many([pagespeed_step, indexing_step])
    await executions.save(execution)

    page_artifacts = RecordingPageExecutionService()
    workflow = AdvanceWorkflow(
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
        flow_document_repository=documents,
    )
    completion = await SubmitExecutionResult(
        execution_repository=executions,
        flow_step_repository=steps,
        flow_document_repository=documents,
        workflow_engine=workflow,
        page_execution_service=page_artifacts,  # type: ignore[arg-type]
    ).execute(
        execution.id,
        ExecutionResultRequest(
            status="succeeded",
            payload={
                "mobile": {"can_index": True, "performance_score": 0.91},
                "desktop": {"can_index": True, "performance_score": 0.97},
            },
        ),
    )

    assert completion is not None
    assert page_artifacts.artifacts == [
        {
            "queue_execution_id": 777,
            "filename": "pagespeed.json",
            "payload": {
                "mobile": {"can_index": True, "performance_score": 0.91},
                "desktop": {"can_index": True, "performance_score": 0.97},
                "stage": "pagespeed",
                "schema_version": "pagespeed.result.v1",
                "flow_id": str(flow.id),
                "execution_id": str(execution.id),
                "orchestrator_status": "succeeded",
                "page_url": "https://example.com/service",
                "campaign_page_id": 179,
            },
        }
    ]


async def test_external_failures_still_create_wordpress_publish_with_partial_results() -> None:
    documents = InMemoryDocumentRepository()
    flows = InMemoryFlowRepository()
    steps = InMemoryFlowStepRepository()
    executions = InMemoryExecutionRepository()
    submitted = await SubmitFlow(
        flow_document_repository=documents,
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
    ).execute(
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            queue_execution_id=299,
            campaign_page_id=179,
            page_url="https://example.com/service",
            requested_capability="seo.main",
            payload={},
        )
    )
    workflow = AdvanceWorkflow(
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
        flow_document_repository=documents,
    )
    submit_result = SubmitExecutionResult(
        execution_repository=executions,
        flow_step_repository=steps,
        flow_document_repository=documents,
        workflow_engine=workflow,
    )
    audit_completion = await submit_result.execute(
        submitted.initial_execution.id,
        ExecutionResultRequest(
            status="succeeded",
            payload={
                "post_bot_payload": [
                    {
                        "campaign_id": "https://example.com",
                        "post_title": "Mi artículo",
                        "image_prompt": "paisaje",
                        "seo_title": "Mi artículo SEO",
                        "meta_description": "Descripción",
                        "content": "<p>Contenido</p>",
                        "keyphrase": "mi artículo",
                        "slug": "mi-articulo",
                        "category": "Blog",
                        "hashtags": "tag1,tag2",
                        "image_alt": "imagen",
                        "create_category": False,
                    }
                ],
                "video_bot_payload": {"title": "Video"},
            },
        ),
    )
    assert audit_completion is not None
    assert audit_completion.workflow is not None
    external_executions = {
        execution.requested_capability: execution
        for execution in audit_completion.workflow.created_executions
    }

    posts_completion = await submit_result.execute(
        external_executions["posts.create"].id,
        ExecutionResultRequest(
            status="failed",
            error="One post failed",
            payload={
                "posts": [
                    {
                        "title": "Publicado",
                        "url": "https://example.com/publicado/",
                        "status": "published",
                    },
                    {
                        "title": "Publicado 2",
                        "url": "https://example.com/publicado-2/",
                        "status": "published",
                    },
                    {
                        "title": "Fallido",
                        "url": "",
                        "status": "failed",
                    },
                ],
                "summary": "2 of 3 posts published",
            },
        ),
    )
    assert posts_completion is not None
    assert posts_completion.execution.status is ExecutionStatus.FAILED
    assert posts_completion.workflow is not None
    assert len(posts_completion.workflow.created_executions) == 1
    post_indexing_execution = posts_completion.workflow.created_executions[0]
    assert post_indexing_execution.requested_capability == "indexing.submit"
    post_indexing_input = documents.documents[post_indexing_execution.input_document_id or ""][
        "payload"
    ]
    assert post_indexing_input["stage"] == "indexing_submit"
    assert post_indexing_input["source"] == "support_posts_result"
    assert post_indexing_input["campaign_page_id"] == 179
    assert post_indexing_input["payload"]["urls_to_index"] == [
        "https://example.com/publicado/",
        "https://example.com/publicado-2/",
    ]

    video_completion = await submit_result.execute(
        external_executions["video.create"].id,
        ExecutionResultRequest(
            status="failed",
            error="Video processing was partial",
            payload={"video_url": "https://example.com/video-parcial"},
        ),
    )

    assert video_completion is not None
    assert video_completion.execution.status is ExecutionStatus.FAILED
    assert video_completion.workflow is not None
    assert video_completion.workflow.flow.current_step is SeoFlowStep.WORDPRESS_PUBLISH
    assert len(video_completion.workflow.created_executions) == 1
    wordpress_execution = video_completion.workflow.created_executions[0]
    assert wordpress_execution.requested_capability == "seo.main"
    wordpress_input = documents.documents[wordpress_execution.input_document_id or ""]["payload"]
    assert wordpress_input["stage"] == "wordpress_publish"
    assert wordpress_input["posts_result"] == {
        "published_posts": [
            {
                "title": "Publicado",
                "url": "https://example.com/publicado/",
                "status": "published",
            },
            {
                "title": "Publicado 2",
                "url": "https://example.com/publicado-2/",
                "status": "published",
            },
        ]
    }
    assert wordpress_input["video_result"] == {"video_url": "https://example.com/video-parcial"}

    wordpress_completion = await submit_result.execute(
        wordpress_execution.id,
        ExecutionResultRequest(status="succeeded", payload=True),
    )
    assert wordpress_completion is not None
    assert wordpress_completion.workflow is not None
    assert wordpress_completion.workflow.completed is False
    assert wordpress_completion.workflow.flow.current_step is SeoFlowStep.PAGESPEED
    assert len(wordpress_completion.workflow.created_executions) == 1
    pagespeed_execution = wordpress_completion.workflow.created_executions[0]
    assert pagespeed_execution.requested_capability == "pagespeed.check"
    pagespeed_input = documents.documents[pagespeed_execution.input_document_id or ""]["payload"]
    assert pagespeed_input["stage"] == "pagespeed"
    assert pagespeed_input["page_url"] == "https://example.com/service"
    assert pagespeed_input["strategy"] == ["mobile", "desktop"]

    pagespeed_completion = await submit_result.execute(
        pagespeed_execution.id,
        ExecutionResultRequest(
            status="succeeded",
            payload={
                "mobile": {"can_index": True},
                "desktop": {"can_index": True},
            },
        ),
    )
    assert pagespeed_completion is not None
    assert pagespeed_completion.workflow is not None
    assert pagespeed_completion.workflow.completed is False
    assert pagespeed_completion.workflow.flow.current_step is SeoFlowStep.INDEXING
    assert len(pagespeed_completion.workflow.created_executions) == 1
    indexing_execution = pagespeed_completion.workflow.created_executions[0]
    assert indexing_execution.requested_capability == "indexing.submit"
    indexing_input = documents.documents[indexing_execution.input_document_id or ""]["payload"]
    assert indexing_input["stage"] == "indexing_submit"
    assert indexing_input["campaign_page_id"] == 179
    assert indexing_input["payload"] == {
        "schema_version": "indexing.submit.input.v1",
        "page_url": "https://example.com/service",
        "urls_to_index": [
            "https://example.com/service",
        ],
        "providers": {
            "google_search_console": True,
            "twoindex_ninja": True,
        },
    }

    final_completion = await submit_result.execute(
        indexing_execution.id,
        ExecutionResultRequest(
            status="succeeded",
            payload={
                "schema_version": "indexing.result.v1",
                "ok": True,
                "status": "submitted",
                "flow_id": str(submitted.flow.id),
                "execution_id": str(indexing_execution.id),
                "campaign_page_id": 179,
                "summary": {
                    "urls_received": 1,
                    "urls_indexable": 1,
                    "urls_submitted": 1,
                    "urls_blocked": 0,
                    "google_search_console_ok": True,
                    "twoindex_ninja_ok": True,
                },
                "url_checks": [],
                "providers": {},
                "artifacts": [],
            },
        ),
    )
    assert final_completion is not None
    assert final_completion.workflow is not None
    assert final_completion.workflow.completed is True


async def test_video_request_times_out_after_ninety_minutes_and_flow_continues() -> None:
    documents = InMemoryDocumentRepository()
    flows = InMemoryFlowRepository()
    steps = InMemoryFlowStepRepository()
    executions = InMemoryExecutionRepository()
    submitted = await SubmitFlow(
        flow_document_repository=documents,
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
    ).execute(
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            queue_execution_id=511,
            campaign_page_id=512,
            page_url="https://example.com/service",
            requested_capability="seo.main",
            payload={},
        )
    )
    workflow = AdvanceWorkflow(
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
        flow_document_repository=documents,
    )
    submit_result = SubmitExecutionResult(
        execution_repository=executions,
        flow_step_repository=steps,
        flow_document_repository=documents,
        workflow_engine=workflow,
    )

    audit_completion = await submit_result.execute(
        submitted.initial_execution.id,
        ExecutionResultRequest(
            status="succeeded",
            payload={
                "post_bot_payload": [
                    {
                        "campaign_id": "https://example.com",
                        "post_title": "Supporting post",
                        "image_prompt": "service",
                        "seo_title": "Supporting post SEO",
                        "meta_description": "Description",
                        "content": "<p>Content</p>",
                        "keyphrase": "supporting post",
                        "slug": "supporting-post",
                        "category": "Blog",
                        "hashtags": "support",
                        "image_alt": "image",
                        "create_category": False,
                    }
                ],
                "video_bot_payload": {"title": "Video"},
            },
        ),
    )
    assert audit_completion is not None
    assert audit_completion.workflow is not None
    external_executions = {
        execution.requested_capability: executions.executions[execution.id]
        for execution in audit_completion.workflow.created_executions
    }
    video_execution = external_executions["video.create"]
    video_execution.created_at = datetime.now(UTC) - timedelta(minutes=91)
    video_execution.updated_at = video_execution.created_at
    await executions.save(video_execution)

    posts_completion = await submit_result.execute(
        external_executions["posts.create"].id,
        ExecutionResultRequest(
            status="succeeded",
            payload={
                "posts": [
                    {
                        "title": "Supporting post",
                        "url": "https://example.com/supporting-post/",
                        "status": "published",
                    }
                ]
            },
        ),
    )

    assert posts_completion is not None
    assert posts_completion.workflow is not None
    flow_steps = {step.step_name: step for step in await steps.list_by_flow(submitted.flow.id)}
    assert flow_steps[SeoFlowStep.VIDEO_REQUEST].status is FlowStepStatus.FAILED
    assert flow_steps[SeoFlowStep.VIDEO_REQUEST].error_message == (
        "Video bot did not respond within 90 minutes"
    )
    assert executions.executions[video_execution.id].status is ExecutionStatus.FAILED
    created_by_capability = {
        execution.requested_capability: execution
        for execution in posts_completion.workflow.created_executions
    }
    assert created_by_capability["seo.main"].step_id == flow_steps[SeoFlowStep.WORDPRESS_PUBLISH].id
    assert created_by_capability["indexing.submit"].step_id is None


async def test_checkpoint_launches_external_work_before_rewrite_finishes() -> None:
    documents = InMemoryDocumentRepository()
    flows = InMemoryFlowRepository()
    steps = InMemoryFlowStepRepository()
    executions = InMemoryExecutionRepository()
    checkpoints = InMemoryExecutionCheckpointRepository()
    submitted = await SubmitFlow(
        flow_document_repository=documents,
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
    ).execute(
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            queue_execution_id=700,
            campaign_page_id=701,
            page_url="https://example.com/service",
            requested_capability="seo.main",
            payload={},
        )
    )
    workflow = AdvanceWorkflow(
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
        flow_document_repository=documents,
    )
    bot_id = UUID("22222222-2222-2222-2222-222222222222")
    initial_execution = executions.executions[submitted.initial_execution.id]
    initial_execution.assign_bot(bot_id)
    initial_execution.mark_queued()
    await executions.save(initial_execution)

    post_payload = {
        "campaign_id": "https://example.com",
        "post_title": "Supporting article",
        "image_prompt": "service illustration",
        "seo_title": "Supporting article SEO",
        "meta_description": "Supporting description",
        "content": "<p>Supporting content</p>",
        "keyphrase": "supporting article",
        "slug": "supporting-article",
        "category": "Blog",
        "hashtags": "support",
        "image_alt": "service illustration",
        "create_category": False,
        "schema_version": "posts.create.v2",
    }
    checkpoint_payload = {
        "schema_version": "seo.audit.checkpoint.v1",
        "audit": {"score": 72},
        "post_bot_payload": [post_payload],
        "video_bot_payload": {
            "schema_version": "video.create.v1",
            "stage": "video_request",
            "flow_id": str(submitted.flow.id),
            "source_execution_id": str(initial_execution.id),
            "campaign_page_id": 701,
            "page_url": "https://example.com/service",
            "title": "Service video",
            "script": "Explain the service",
        },
        "rewrite_brief": {"expected_posts": 1, "expects_video": True},
        "debug": {"source": "unit-test"},
    }
    processor = ProcessExecutionCheckpoint(
        execution_repository=executions,
        checkpoint_repository=checkpoints,
        flow_repository=flows,
        flow_step_repository=steps,
        flow_document_repository=documents,
        workflow_engine=workflow,
    )

    checkpoint_completion = await processor.execute(
        initial_execution.id,
        bot_id,
        "external_payloads_ready",
        checkpoint_payload,
    )

    assert checkpoint_completion.execution.status is ExecutionStatus.RUNNING
    assert checkpoint_completion.execution.internal_state == "page_rewrite_running"
    assert len(checkpoint_completion.created_executions) == 2
    external_executions = {
        execution.requested_capability: execution
        for execution in checkpoint_completion.created_executions
    }
    posts_input = documents.documents[external_executions["posts.create"].input_document_id or ""][
        "payload"
    ]
    assert posts_input["payload"] == [post_payload]
    video_input = documents.documents[external_executions["video.create"].input_document_id or ""][
        "payload"
    ]
    assert video_input["payload"] == checkpoint_payload["video_bot_payload"]

    duplicate = await processor.execute(
        initial_execution.id,
        bot_id,
        "external_payloads_ready",
        checkpoint_payload,
    )
    assert duplicate.duplicate is True
    assert duplicate.created_executions == []

    submit_result = SubmitExecutionResult(
        execution_repository=executions,
        flow_step_repository=steps,
        flow_document_repository=documents,
        workflow_engine=workflow,
    )
    await submit_result.execute(
        external_executions["posts.create"].id,
        ExecutionResultRequest(
            status="succeeded",
            payload={
                "posts": [
                    {
                        "title": "Supporting article",
                        "url": "https://example.com/supporting-article/",
                        "status": "published",
                    }
                ]
            },
        ),
    )
    video_completion = await submit_result.execute(
        external_executions["video.create"].id,
        ExecutionResultRequest(
            status="succeeded",
            payload={"video_url": "https://example.com/video"},
        ),
    )
    assert video_completion is not None
    assert video_completion.workflow is not None
    assert video_completion.workflow.created_executions == []

    rewrite_result = {
        "schema_version": "seo.rewrite.v1",
        "ok": True,
        "stage": "page_rewrite",
        "campaign_page_id": 701,
        "page_update": {
            "updated_elementor_data": [{"id": "hero", "settings": {}}],
            "extra_meta": {"yoast_wpseo_title": "Updated title"},
            "pipeline": {"status": "ready"},
        },
        "pending_insertions": {"posts": [], "video": None},
        "rewrite_report": {"status": "ok"},
    }
    rewrite_completion = await submit_result.execute(
        initial_execution.id,
        ExecutionResultRequest(status="succeeded", payload=rewrite_result),
    )
    assert rewrite_completion is not None
    assert rewrite_completion.workflow is not None
    assert len(rewrite_completion.workflow.created_executions) == 1
    wordpress_execution = rewrite_completion.workflow.created_executions[0]
    wordpress_input = documents.documents[wordpress_execution.input_document_id or ""]["payload"]
    assert wordpress_input["source_rewrite_execution_id"] == str(initial_execution.id)
    assert wordpress_input["rewrite_result"] == rewrite_result
    assert wordpress_input["posts_result"]["published_posts"][0]["url"] == (
        "https://example.com/supporting-article/"
    )
    assert wordpress_input["video_result"] == {"video_url": "https://example.com/video"}


async def test_checkpoint_skips_empty_external_dependencies() -> None:
    documents = InMemoryDocumentRepository()
    flows = InMemoryFlowRepository()
    steps = InMemoryFlowStepRepository()
    executions = InMemoryExecutionRepository()
    checkpoints = InMemoryExecutionCheckpointRepository()
    submitted = await SubmitFlow(
        flow_document_repository=documents,
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
    ).execute(
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            queue_execution_id=800,
            campaign_page_id=801,
            page_url="https://example.com/no-assets",
            requested_capability="seo.main",
            payload={},
        )
    )
    workflow = AdvanceWorkflow(
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
        flow_document_repository=documents,
    )
    bot_id = UUID("33333333-3333-3333-3333-333333333333")
    initial_execution = executions.executions[submitted.initial_execution.id]
    initial_execution.assign_bot(bot_id)
    initial_execution.mark_queued()
    await executions.save(initial_execution)

    completion = await ProcessExecutionCheckpoint(
        execution_repository=executions,
        checkpoint_repository=checkpoints,
        flow_repository=flows,
        flow_step_repository=steps,
        flow_document_repository=documents,
        workflow_engine=workflow,
    ).execute(
        initial_execution.id,
        bot_id,
        "external_payloads_ready",
        {
            "schema_version": "seo.audit.checkpoint.v1",
            "audit": {"status": "ready"},
            "post_bot_payload": [],
            "video_bot_payload": {"status": "skipped"},
            "rewrite_brief": {
                "expected_posts": 0,
                "expects_video": False,
            },
        },
    )

    assert completion.created_executions == []
    flow_steps = {step.step_name: step for step in await steps.list_by_flow(submitted.flow.id)}
    assert flow_steps[SeoFlowStep.SEO_AUDIT].status is FlowStepStatus.RUNNING
    assert flow_steps[SeoFlowStep.SUPPORT_POSTS].status is FlowStepStatus.SKIPPED
    assert flow_steps[SeoFlowStep.VIDEO_REQUEST].status is FlowStepStatus.SKIPPED

    rewrite_result = {
        "schema_version": "seo.rewrite.v1",
        "ok": True,
        "stage": "page_rewrite",
        "campaign_page_id": 801,
        "page_update": {
            "updated_elementor_data": [{"id": "content", "settings": {}}],
        },
        "pending_insertions": {},
    }
    rewrite_completion = await SubmitExecutionResult(
        execution_repository=executions,
        flow_step_repository=steps,
        flow_document_repository=documents,
        workflow_engine=workflow,
    ).execute(
        initial_execution.id,
        ExecutionResultRequest(status="succeeded", payload=rewrite_result),
    )

    assert rewrite_completion is not None
    assert rewrite_completion.workflow is not None
    assert len(rewrite_completion.workflow.created_executions) == 1
    wordpress_execution = rewrite_completion.workflow.created_executions[0]
    wordpress_input = documents.documents[wordpress_execution.input_document_id or ""]["payload"]
    assert wordpress_input["rewrite_result"] == rewrite_result
    assert wordpress_input["posts_result"] == {"published_posts": []}
    assert wordpress_input["video_result"] == {"skipped": True}


async def test_checkpoint_uses_existing_posts_without_launching_posts_bot() -> None:
    documents = InMemoryDocumentRepository()
    flows = InMemoryFlowRepository()
    steps = InMemoryFlowStepRepository()
    executions = InMemoryExecutionRepository()
    checkpoints = InMemoryExecutionCheckpointRepository()
    submitted = await SubmitFlow(
        flow_document_repository=documents,
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
    ).execute(
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            queue_execution_id=900,
            campaign_page_id=901,
            page_url="https://example.com/service",
            requested_capability="seo.main",
            payload={"support_posts": {"mode": "auto"}},
        )
    )
    workflow = AdvanceWorkflow(
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
        flow_document_repository=documents,
    )
    bot_id = UUID("44444444-4444-4444-4444-444444444444")
    initial_execution = executions.executions[submitted.initial_execution.id]
    initial_execution.assign_bot(bot_id)
    initial_execution.mark_queued()
    await executions.save(initial_execution)

    completion = await ProcessExecutionCheckpoint(
        execution_repository=executions,
        checkpoint_repository=checkpoints,
        flow_repository=flows,
        flow_step_repository=steps,
        flow_document_repository=documents,
        workflow_engine=workflow,
    ).execute(
        initial_execution.id,
        bot_id,
        "external_payloads_ready",
        {
            "schema_version": "seo.audit.checkpoint.v1",
            "audit": {"status": "ready"},
            "post_bot_payload": [],
            "support_posts_plan": {
                "mode": "auto",
                "existing_posts": [
                    {
                        "title": "Existing state post",
                        "url": "https://example.com/existing-state-post/",
                    }
                ],
            },
            "video_bot_payload": {"status": "skipped"},
            "rewrite_brief": {"expected_posts": 1, "expects_video": False},
        },
    )

    assert completion.created_executions == []
    flow_steps = {step.step_name: step for step in await steps.list_by_flow(submitted.flow.id)}
    assert flow_steps[SeoFlowStep.SUPPORT_POSTS].status is FlowStepStatus.SUCCEEDED

    rewrite_result = {
        "schema_version": "seo.rewrite.v1",
        "ok": True,
        "stage": "page_rewrite",
        "campaign_page_id": 901,
        "page_update": {"updated_elementor_data": [{"id": "content"}]},
        "pending_insertions": {},
    }
    rewrite_completion = await SubmitExecutionResult(
        execution_repository=executions,
        flow_step_repository=steps,
        flow_document_repository=documents,
        workflow_engine=workflow,
    ).execute(
        initial_execution.id,
        ExecutionResultRequest(status="succeeded", payload=rewrite_result),
    )

    assert rewrite_completion is not None
    assert rewrite_completion.workflow is not None
    wordpress_execution = rewrite_completion.workflow.created_executions[0]
    wordpress_input = documents.documents[wordpress_execution.input_document_id or ""]["payload"]
    assert wordpress_input["posts_result"]["existing_posts"] == [
        {
            "title": "Existing state post",
            "url": "https://example.com/existing-state-post/",
            "status": "published",
        }
    ]
    assert (
        wordpress_input["posts_result"]["published_posts"]
        == (wordpress_input["posts_result"]["existing_posts"])
    )


async def test_checkpoint_mode_none_skips_posts_with_required_zero() -> None:
    documents = InMemoryDocumentRepository()
    flows = InMemoryFlowRepository()
    steps = InMemoryFlowStepRepository()
    executions = InMemoryExecutionRepository()
    checkpoints = InMemoryExecutionCheckpointRepository()
    submitted = await SubmitFlow(
        flow_document_repository=documents,
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
    ).execute(
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            queue_execution_id=910,
            campaign_page_id=911,
            page_url="https://example.com/service",
            requested_capability="seo.main",
            payload={"support_posts": {"mode": "none"}},
        )
    )
    workflow = AdvanceWorkflow(
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
        flow_document_repository=documents,
    )
    bot_id = UUID("55555555-5555-5555-5555-555555555555")
    initial_execution = executions.executions[submitted.initial_execution.id]
    initial_execution.assign_bot(bot_id)
    initial_execution.mark_queued()
    await executions.save(initial_execution)

    completion = await ProcessExecutionCheckpoint(
        execution_repository=executions,
        checkpoint_repository=checkpoints,
        flow_repository=flows,
        flow_step_repository=steps,
        flow_document_repository=documents,
        workflow_engine=workflow,
    ).execute(
        initial_execution.id,
        bot_id,
        "external_payloads_ready",
        {
            "schema_version": "seo.audit.checkpoint.v1",
            "audit": {"status": "ready"},
            "post_bot_payload": [],
            "support_posts_plan": {"mode": "none"},
            "video_bot_payload": {"status": "skipped"},
            "rewrite_brief": {"expected_posts": 0, "expects_video": False},
        },
    )

    assert completion.created_executions == []
    flow_steps = {step.step_name: step for step in await steps.list_by_flow(submitted.flow.id)}
    assert flow_steps[SeoFlowStep.SUPPORT_POSTS].status is FlowStepStatus.SKIPPED

    rewrite_result = {
        "schema_version": "seo.rewrite.v1",
        "ok": True,
        "stage": "page_rewrite",
        "campaign_page_id": 911,
        "page_update": {"updated_elementor_data": [{"id": "content"}]},
        "pending_insertions": {},
    }
    rewrite_completion = await SubmitExecutionResult(
        execution_repository=executions,
        flow_step_repository=steps,
        flow_document_repository=documents,
        workflow_engine=workflow,
    ).execute(
        initial_execution.id,
        ExecutionResultRequest(status="succeeded", payload=rewrite_result),
    )

    assert rewrite_completion is not None
    wordpress_execution = rewrite_completion.workflow.created_executions[0]  # type: ignore[union-attr]
    wordpress_input = documents.documents[wordpress_execution.input_document_id or ""]["payload"]
    assert wordpress_input["posts_result"]["published_posts"] == []
    assert wordpress_input["posts_result"]["support_posts_required"] == 0


async def test_checkpoint_legacy_two_limits_posts_payload_to_two_items() -> None:
    documents = InMemoryDocumentRepository()
    flows = InMemoryFlowRepository()
    steps = InMemoryFlowStepRepository()
    executions = InMemoryExecutionRepository()
    checkpoints = InMemoryExecutionCheckpointRepository()
    submitted = await SubmitFlow(
        flow_document_repository=documents,
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
    ).execute(
        FlowSubmitRequest(
            flow_type="commercial_page_seo",
            queue_execution_id=920,
            campaign_page_id=921,
            page_url="https://example.com/service",
            requested_capability="seo.main",
            payload={"support_posts": {"mode": "legacy_two"}},
        )
    )
    workflow = AdvanceWorkflow(
        flow_repository=flows,
        flow_step_repository=steps,
        execution_repository=executions,
        flow_document_repository=documents,
    )
    bot_id = UUID("66666666-6666-6666-6666-666666666666")
    initial_execution = executions.executions[submitted.initial_execution.id]
    initial_execution.assign_bot(bot_id)
    initial_execution.mark_queued()
    await executions.save(initial_execution)
    post_payload = {
        "campaign_id": "https://example.com",
        "post_title": "Supporting article",
        "image_prompt": "service illustration",
        "seo_title": "Supporting article SEO",
        "meta_description": "Supporting description",
        "content": "<p>Supporting content</p>",
        "keyphrase": "supporting article",
        "slug": "supporting-article",
        "category": "Blog",
        "hashtags": "support",
        "image_alt": "service illustration",
        "create_category": False,
    }

    completion = await ProcessExecutionCheckpoint(
        execution_repository=executions,
        checkpoint_repository=checkpoints,
        flow_repository=flows,
        flow_step_repository=steps,
        flow_document_repository=documents,
        workflow_engine=workflow,
    ).execute(
        initial_execution.id,
        bot_id,
        "external_payloads_ready",
        {
            "schema_version": "seo.audit.checkpoint.v1",
            "audit": {"status": "ready"},
            "post_bot_payload": [
                {**post_payload, "post_title": "Post 1", "slug": "post-1"},
                {**post_payload, "post_title": "Post 2", "slug": "post-2"},
                {**post_payload, "post_title": "Post 3", "slug": "post-3"},
            ],
            "support_posts_plan": {"mode": "legacy_two"},
            "video_bot_payload": {"status": "skipped"},
            "rewrite_brief": {"expected_posts": 2, "expects_video": False},
        },
    )

    assert len(completion.created_executions) == 1
    posts_execution = completion.created_executions[0]
    posts_input = documents.documents[posts_execution.input_document_id or ""]["payload"]
    assert posts_input["stage"] == "support_posts"
    assert len(posts_input["payload"]) == 2
    assert [post["slug"] for post in posts_input["payload"]] == ["post-1", "post-2"]
