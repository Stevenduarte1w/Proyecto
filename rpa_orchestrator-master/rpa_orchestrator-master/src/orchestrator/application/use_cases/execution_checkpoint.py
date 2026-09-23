from __future__ import annotations

from typing import Any
from uuid import UUID

from orchestrator.application.dtos import (
    ExecutionCheckpointResponse,
    ExecutionResponse,
)
from orchestrator.application.use_cases.advance_workflow import AdvanceWorkflow
from orchestrator.application.use_cases.execution_documents import (
    _post_payload_validation_error,
)
from orchestrator.domain.entities import (
    ExecutionCheckpoint,
    ExecutionCheckpointStatus,
    ExecutionStatus,
    FlowStepStatus,
    SeoFlowStep,
)
from orchestrator.domain.ports import (
    ExecutionCheckpointRepository,
    ExecutionRepository,
    FlowDocumentRepository,
    FlowRepository,
    FlowStepRepository,
)

EXTERNAL_PAYLOADS_READY = "external_payloads_ready"
CHECKPOINT_SCHEMA_VERSION = "seo.audit.checkpoint.v1"


class ExecutionEventError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StartExecution:
    def __init__(
        self,
        execution_repository: ExecutionRepository,
        flow_step_repository: FlowStepRepository,
    ) -> None:
        self._execution_repository = execution_repository
        self._flow_step_repository = flow_step_repository

    async def execute(self, execution_id: UUID, actor_bot_id: UUID) -> ExecutionResponse:
        execution = await self._execution_repository.get(execution_id)
        if execution is None:
            raise ExecutionEventError("not_found", "Execution not found")
        _require_owner(execution.bot_id, actor_bot_id)
        if execution.status is ExecutionStatus.RUNNING:
            return ExecutionResponse.model_validate(execution)
        if execution.status is not ExecutionStatus.QUEUED:
            raise ExecutionEventError(
                "invalid_state",
                f"Cannot start execution from status {execution.status.value}",
            )

        step = None
        internal_state = "running"
        if execution.step_id is not None:
            step = await self._flow_step_repository.get(execution.step_id)
            if step is not None:
                internal_state = (
                    "audit_running"
                    if step.step_name is SeoFlowStep.SEO_AUDIT
                    else f"{step.step_name.value}_running"
                )

        execution.mark_running(internal_state)
        saved = await self._execution_repository.save(execution)
        if step is not None:
            step.mark_running()
            await self._flow_step_repository.save(step)
        return ExecutionResponse.model_validate(saved)


class ProcessExecutionCheckpoint:
    def __init__(
        self,
        execution_repository: ExecutionRepository,
        checkpoint_repository: ExecutionCheckpointRepository,
        flow_repository: FlowRepository,
        flow_step_repository: FlowStepRepository,
        flow_document_repository: FlowDocumentRepository,
        workflow_engine: AdvanceWorkflow,
    ) -> None:
        self._execution_repository = execution_repository
        self._checkpoint_repository = checkpoint_repository
        self._flow_repository = flow_repository
        self._flow_step_repository = flow_step_repository
        self._flow_document_repository = flow_document_repository
        self._workflow_engine = workflow_engine

    async def execute(
        self,
        execution_id: UUID,
        actor_bot_id: UUID,
        checkpoint_name: str,
        payload: Any,
        reported_flow_id: str | None = None,
        reported_capability: str | None = None,
    ) -> ExecutionCheckpointResponse:
        execution = await self._execution_repository.get(execution_id)
        if execution is None:
            raise ExecutionEventError("not_found", "Execution not found")
        _require_owner(execution.bot_id, actor_bot_id)
        if reported_flow_id is not None and reported_flow_id != execution.flow_id:
            raise ExecutionEventError(
                "invalid_checkpoint",
                "Checkpoint flow_id does not match the execution",
            )
        if (
            reported_capability is not None
            and reported_capability != execution.requested_capability
        ):
            raise ExecutionEventError(
                "invalid_checkpoint",
                "Checkpoint capability does not match the execution",
            )
        if checkpoint_name != EXTERNAL_PAYLOADS_READY:
            raise ExecutionEventError(
                "invalid_checkpoint",
                f"Unsupported checkpoint: {checkpoint_name}",
            )
        if execution.step_id is None:
            raise ExecutionEventError("invalid_state", "Execution has no workflow step")
        step = await self._flow_step_repository.get(execution.step_id)
        if step is None or step.step_name is not SeoFlowStep.SEO_AUDIT:
            raise ExecutionEventError(
                "invalid_state",
                "external_payloads_ready is only valid for seo_audit",
            )
        if execution.status not in {ExecutionStatus.QUEUED, ExecutionStatus.RUNNING}:
            raise ExecutionEventError(
                "invalid_state",
                f"Cannot checkpoint execution from status {execution.status.value}",
            )

        existing = await self._checkpoint_repository.get(execution.id, checkpoint_name)
        if existing is not None and existing.status is ExecutionCheckpointStatus.PROCESSED:
            return ExecutionCheckpointResponse(
                execution=ExecutionResponse.model_validate(execution),
                checkpoint=checkpoint_name,
                duplicate=True,
            )
        if existing is not None and existing.status is ExecutionCheckpointStatus.FAILED:
            raise ExecutionEventError(
                "invalid_checkpoint",
                existing.error_message or "Checkpoint previously failed validation",
            )

        validation_error = _checkpoint_validation_error(payload)
        if validation_error is not None:
            await self._fail_invalid_checkpoint(
                execution=execution,
                step=step,
                checkpoint_name=checkpoint_name,
                payload=payload,
                reason=validation_error,
            )
            raise ExecutionEventError("invalid_checkpoint", validation_error)

        checkpoint = existing
        if checkpoint is None:
            document_id = await self._flow_document_repository.store_document(
                flow_id=execution.flow_id,
                step_name=step.step_name.value,
                document_type="execution_checkpoint",
                payload={
                    "checkpoint": checkpoint_name,
                    "payload": payload,
                },
                execution_id=execution.id,
            )
            proposed = ExecutionCheckpoint(
                flow_id=UUID(execution.flow_id),
                execution_id=execution.id,
                checkpoint=checkpoint_name,
                mongo_document_id=document_id,
            )
            checkpoint, created = await self._checkpoint_repository.create(proposed)
            if not created and checkpoint.status is ExecutionCheckpointStatus.PROCESSED:
                return ExecutionCheckpointResponse(
                    execution=ExecutionResponse.model_validate(execution),
                    checkpoint=checkpoint_name,
                    duplicate=True,
                )

        execution.mark_running("page_rewrite_running")
        saved_execution = await self._execution_repository.save(execution)
        if step.status in {FlowStepStatus.QUEUED, FlowStepStatus.PENDING}:
            step.mark_running()
            await self._flow_step_repository.save(step)

        workflow = await self._workflow_engine.process_external_payloads_checkpoint(
            UUID(execution.flow_id),
            execution.id,
            payload,
        )
        if workflow is None:
            raise ExecutionEventError("not_found", "Workflow not found")

        checkpoint.mark_processed()
        await self._checkpoint_repository.save(checkpoint)
        return ExecutionCheckpointResponse(
            execution=ExecutionResponse.model_validate(saved_execution),
            checkpoint=checkpoint_name,
            created_executions=workflow.created_executions,
            dispatched_executions=workflow.dispatched_executions,
        )

    async def _fail_invalid_checkpoint(
        self,
        *,
        execution: Any,
        step: Any,
        checkpoint_name: str,
        payload: Any,
        reason: str,
    ) -> None:
        document_id = await self._flow_document_repository.store_document(
            flow_id=execution.flow_id,
            step_name=step.step_name.value,
            document_type="invalid_execution_checkpoint",
            payload={
                "checkpoint": checkpoint_name,
                "payload": payload,
                "error": reason,
            },
            execution_id=execution.id,
        )
        checkpoint = ExecutionCheckpoint(
            flow_id=UUID(execution.flow_id),
            execution_id=execution.id,
            checkpoint=checkpoint_name,
            mongo_document_id=document_id,
        )
        checkpoint.mark_failed(reason)
        stored, created = await self._checkpoint_repository.create(checkpoint)
        if created:
            await self._checkpoint_repository.save(checkpoint)
        elif stored.status is not ExecutionCheckpointStatus.FAILED:
            stored.mark_failed(reason)
            await self._checkpoint_repository.save(stored)

        execution.mark_failed(reason, document_id)
        await self._execution_repository.save(execution)
        step.mark_failed(reason, document_id)
        await self._flow_step_repository.save(step)
        flow = await self._flow_repository.get(UUID(execution.flow_id))
        if flow is not None:
            flow.mark_failed()
            await self._flow_repository.save(flow)


def _checkpoint_validation_error(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return "Checkpoint payload must be a JSON object"
    if payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        return f"Checkpoint schema_version must be {CHECKPOINT_SCHEMA_VERSION}"
    missing = [
        field
        for field in ("audit", "post_bot_payload", "video_bot_payload", "rewrite_brief")
        if field not in payload
    ]
    if missing:
        return f"Checkpoint payload is missing required fields: {', '.join(missing)}"
    if not isinstance(payload["audit"], dict):
        return "Checkpoint field audit must be a JSON object"
    posts = payload["post_bot_payload"]
    if not isinstance(posts, list):
        return "Checkpoint field post_bot_payload must be a JSON array"
    posts_to_validate = (
        posts[:2] if _support_posts_mode(payload) == "legacy_two" else posts
    )
    for index, post in enumerate(posts_to_validate):
        error = _post_payload_validation_error(post, index)
        if error is not None:
            return error
    support_posts_plan = payload.get("support_posts_plan")
    if support_posts_plan is not None and not isinstance(support_posts_plan, dict):
        return "Checkpoint field support_posts_plan must be a JSON object"
    if isinstance(support_posts_plan, dict):
        existing_posts = support_posts_plan.get("existing_posts")
        if existing_posts is not None and not isinstance(existing_posts, list):
            return "Checkpoint field support_posts_plan.existing_posts must be a JSON array"
    if not isinstance(payload["video_bot_payload"], dict):
        return "Checkpoint field video_bot_payload must be a JSON object"
    if not isinstance(payload["rewrite_brief"], dict):
        return "Checkpoint field rewrite_brief must be a JSON object"
    return None


def _support_posts_mode(payload: dict[str, Any]) -> str | None:
    support_posts = payload.get("support_posts")
    if isinstance(support_posts, dict) and isinstance(support_posts.get("mode"), str):
        return str(support_posts["mode"])
    support_posts_plan = payload.get("support_posts_plan")
    if isinstance(support_posts_plan, dict):
        mode = support_posts_plan.get("mode") or support_posts_plan.get("requested_mode")
        if isinstance(mode, str):
            return mode
    return None


def _require_owner(execution_bot_id: UUID | None, actor_bot_id: UUID) -> None:
    if execution_bot_id != actor_bot_id:
        raise ExecutionEventError(
            "forbidden",
            "Execution is assigned to a different bot",
        )
