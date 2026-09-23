from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

from orchestrator.application.dtos import ExecutionResultRequest
from orchestrator.application.use_cases.advance_workflow import AdvanceWorkflow
from orchestrator.application.use_cases.execution_documents import SubmitExecutionResult
from orchestrator.domain.entities import (
    Execution,
    ExecutionStatus,
    Flow,
    FlowStatus,
    FlowStep,
    FlowStepStatus,
    SeoFlowStep,
)
from orchestrator.domain.indexing import indexing_result_error
from orchestrator.domain.pagespeed import indexing_denial_reason


@pytest.mark.parametrize(
    ("payload", "denied_profile"),
    [
        ({"mobile": {"can_index": False}, "desktop": {"can_index": True}}, "mobile"),
        ({"mobile": {"can_index": True}, "desktop": {"can_index": False}}, "desktop"),
    ],
)
def test_pagespeed_denies_indexing_when_any_profile_rejects(
    payload: dict[str, Any],
    denied_profile: str,
) -> None:
    reason = indexing_denial_reason(payload)

    assert reason is not None
    assert denied_profile in reason


def test_pagespeed_authorizes_indexing_when_profiles_allow_it() -> None:
    payload = {
        "mobile": {"can_index": True},
        "desktop": {"can_index": True},
    }

    assert indexing_denial_reason(payload) is None


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        ({"mobile": {"can_index": True}}, "missing profiles"),
        (
            {"mobile": {}, "desktop": {"can_index": True}},
            "require boolean can_index",
        ),
        (
            {"mobile": [], "desktop": {"can_index": True}},
            "must be JSON objects",
        ),
    ],
)
def test_pagespeed_rejects_incomplete_results(
    payload: dict[str, Any],
    expected_error: str,
) -> None:
    reason = indexing_denial_reason(payload)

    assert reason is not None
    assert expected_error in reason


def test_indexing_result_requires_submitted_success_contract() -> None:
    valid = {
        "schema_version": "indexing.result.v1",
        "ok": True,
        "status": "submitted",
        "summary": {
            "urls_received": 3,
            "urls_indexable": 3,
            "urls_submitted": 3,
            "urls_blocked": 0,
        },
    }

    assert indexing_result_error(valid) is None
    assert indexing_result_error({**valid, "ok": False}) is not None
    assert indexing_result_error({**valid, "status": "failed"}) is not None


class InMemoryFlowRepository:
    def __init__(self, flow: Flow) -> None:
        self.flow = flow

    async def get(self, flow_id: UUID) -> Flow | None:
        return self.flow if self.flow.id == flow_id else None

    async def save(self, flow: Flow) -> Flow:
        self.flow = flow
        return flow


class InMemoryFlowStepRepository:
    def __init__(self, steps: list[FlowStep]) -> None:
        self.steps = {step.id: step for step in steps}

    async def get(self, step_id: UUID) -> FlowStep | None:
        return self.steps.get(step_id)

    async def list_by_flow(self, flow_id: UUID) -> list[FlowStep]:
        return sorted(
            (step for step in self.steps.values() if step.flow_id == flow_id),
            key=lambda step: step.position,
        )

    async def save(self, step: FlowStep) -> FlowStep:
        self.steps[step.id] = step
        return step


class InMemoryExecutionRepository:
    def __init__(self, execution: Execution) -> None:
        self.executions = {execution.id: execution}

    async def get(self, execution_id: UUID) -> Execution | None:
        return self.executions.get(execution_id)

    async def save(self, execution: Execution) -> Execution:
        self.executions[execution.id] = execution
        return execution


class InMemoryFlowDocumentRepository:
    def __init__(self) -> None:
        self.stored_document: dict[str, Any] | None = None

    async def store_document(
        self,
        flow_id: str,
        step_name: str,
        document_type: str,
        payload: dict[str, Any],
        execution_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> str:
        self.stored_document = {
            "flow_id": flow_id,
            "step_name": step_name,
            "document_type": document_type,
            "payload": payload,
            "execution_id": execution_id,
            "correlation_id": correlation_id,
        }
        return "pagespeed-output-document"


def test_rejected_pagespeed_result_fails_flow_and_does_not_start_indexing() -> None:
    asyncio.run(_submit_rejected_pagespeed_result())


async def _submit_rejected_pagespeed_result() -> None:
    flow = Flow(flow_type="commercial_page_seo", page_url="https://example.com")
    pagespeed_step = FlowStep(
        flow_id=flow.id,
        step_name=SeoFlowStep.PAGESPEED,
        position=15,
        requested_capability="pagespeed.check",
    )
    indexing_step = FlowStep(
        flow_id=flow.id,
        step_name=SeoFlowStep.INDEXING,
        position=16,
        requested_capability="indexing.submit",
    )
    execution = Execution(
        flow_id=str(flow.id),
        requested_capability="pagespeed.check",
        step_id=pagespeed_step.id,
    )
    pagespeed_step.assign_execution(execution.id)

    flow_repository = InMemoryFlowRepository(flow)
    step_repository = InMemoryFlowStepRepository([pagespeed_step, indexing_step])
    execution_repository = InMemoryExecutionRepository(execution)
    document_repository = InMemoryFlowDocumentRepository()
    workflow = AdvanceWorkflow(
        flow_repository=flow_repository,
        flow_step_repository=step_repository,
        execution_repository=execution_repository,
        flow_document_repository=document_repository,
    )
    payload = {
        "url": "https://example.com",
        "mobile": {"can_index": True},
        "desktop": {"can_index": False},
        "summary": "PageSpeed revisado correctamente",
    }

    completion = await SubmitExecutionResult(
        execution_repository=execution_repository,
        flow_step_repository=step_repository,
        flow_document_repository=document_repository,
        workflow_engine=workflow,
    ).execute(
        execution.id,
        ExecutionResultRequest(status="succeeded", payload=payload),
    )

    assert completion is not None
    assert completion.execution.status is ExecutionStatus.FAILED
    assert completion.execution.error_message is not None
    assert "desktop" in completion.execution.error_message
    assert pagespeed_step.status is FlowStepStatus.FAILED
    assert indexing_step.status is FlowStepStatus.PENDING
    assert flow_repository.flow.status is FlowStatus.FAILED
    assert len(execution_repository.executions) == 1
    assert document_repository.stored_document is not None
    assert document_repository.stored_document["document_type"] == "failed"
    assert document_repository.stored_document["payload"] == payload


async def test_wordpress_publish_accepts_boolean_true() -> None:
    flow = Flow(flow_type="commercial_page_seo", page_url="https://example.com")
    publish_step = FlowStep(
        flow_id=flow.id,
        step_name=SeoFlowStep.WORDPRESS_PUBLISH,
        position=1,
        requested_capability="seo.main",
    )
    execution = Execution(
        flow_id=str(flow.id),
        requested_capability="seo.main",
        step_id=publish_step.id,
    )
    publish_step.assign_execution(execution.id)
    flow_repository = InMemoryFlowRepository(flow)
    step_repository = InMemoryFlowStepRepository([publish_step])
    execution_repository = InMemoryExecutionRepository(execution)
    document_repository = InMemoryFlowDocumentRepository()
    workflow = AdvanceWorkflow(
        flow_repository=flow_repository,
        flow_step_repository=step_repository,
        execution_repository=execution_repository,
        flow_document_repository=document_repository,
    )

    completion = await SubmitExecutionResult(
        execution_repository=execution_repository,
        flow_step_repository=step_repository,
        flow_document_repository=document_repository,
        workflow_engine=workflow,
    ).execute(
        execution.id,
        ExecutionResultRequest(status="succeeded", payload=True),
    )

    assert completion is not None
    assert completion.execution.status is ExecutionStatus.SUCCEEDED
    assert flow_repository.flow.status is FlowStatus.SUCCEEDED


async def test_wordpress_publish_false_blocks_following_steps() -> None:
    flow = Flow(flow_type="commercial_page_seo", page_url="https://example.com")
    publish_step = FlowStep(
        flow_id=flow.id,
        step_name=SeoFlowStep.WORDPRESS_PUBLISH,
        position=1,
        requested_capability="seo.main",
    )
    pagespeed_step = FlowStep(
        flow_id=flow.id,
        step_name=SeoFlowStep.PAGESPEED,
        position=2,
        requested_capability="pagespeed.check",
    )
    indexing_step = FlowStep(
        flow_id=flow.id,
        step_name=SeoFlowStep.INDEXING,
        position=3,
        requested_capability="indexing.submit",
    )
    execution = Execution(
        flow_id=str(flow.id),
        requested_capability="seo.main",
        step_id=publish_step.id,
    )
    publish_step.assign_execution(execution.id)
    flow_repository = InMemoryFlowRepository(flow)
    step_repository = InMemoryFlowStepRepository(
        [publish_step, pagespeed_step, indexing_step]
    )
    execution_repository = InMemoryExecutionRepository(execution)
    document_repository = InMemoryFlowDocumentRepository()
    workflow = AdvanceWorkflow(
        flow_repository=flow_repository,
        flow_step_repository=step_repository,
        execution_repository=execution_repository,
        flow_document_repository=document_repository,
    )

    completion = await SubmitExecutionResult(
        execution_repository=execution_repository,
        flow_step_repository=step_repository,
        flow_document_repository=document_repository,
        workflow_engine=workflow,
    ).execute(
        execution.id,
        ExecutionResultRequest(status="failed", payload=False),
    )

    assert completion is not None
    assert completion.execution.status is ExecutionStatus.FAILED
    assert flow_repository.flow.status is FlowStatus.FAILED
    assert pagespeed_step.status is FlowStepStatus.PENDING
    assert indexing_step.status is FlowStepStatus.PENDING
    assert completion.workflow is not None
    assert completion.workflow.created_executions == []
