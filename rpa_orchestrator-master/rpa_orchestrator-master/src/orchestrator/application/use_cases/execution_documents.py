from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import structlog

from orchestrator.application.dtos import (
    ExecutionCompletionResponse,
    ExecutionResponse,
    ExecutionResultRequest,
)
from orchestrator.application.use_cases.advance_workflow import AdvanceWorkflow
from orchestrator.application.use_cases.page_executions import PageExecutionService
from orchestrator.domain.entities import (
    ExecutionStatus,
    FlowStatus,
    FlowStepStatus,
    SeoFlowStep,
)
from orchestrator.domain.indexing import INDEXING_CAPABILITY, indexing_result_error
from orchestrator.domain.instagram import (
    INSTAGRAM_MADURACION_CAPABILITY,
    INSTAGRAM_PROSPECTING_CAPABILITY,
)
from orchestrator.domain.pagespeed import PAGESPEED_CAPABILITY, indexing_denial_reason
from orchestrator.domain.ports import (
    ExecutionRepository,
    FlowDocumentRepository,
    FlowStepRepository,
    SeoAgentManagementRepository,
)

logger = structlog.get_logger(__name__)

POST_BOT_PAYLOAD_FIELDS = {
    "campaign_id": str,
    "post_title": str,
    "image_prompt": str,
    "seo_title": str,
    "meta_description": str,
    "content": str,
    "keyphrase": str,
    "slug": str,
    "category": str,
    "hashtags": str,
    "image_alt": str,
    "create_category": bool,
}


class GetExecutionInput:
    def __init__(
        self,
        execution_repository: ExecutionRepository,
        flow_document_repository: FlowDocumentRepository,
    ) -> None:
        self._execution_repository = execution_repository
        self._flow_document_repository = flow_document_repository

    async def execute(self, execution_id: UUID) -> dict[str, Any] | None:
        execution = await self._execution_repository.get(execution_id)
        if execution is None or execution.input_document_id is None:
            return None
        document = await self._flow_document_repository.get_document(execution.input_document_id)
        if document is None:
            return None
        if execution.requested_capability in {
            INSTAGRAM_MADURACION_CAPABILITY,
            INSTAGRAM_PROSPECTING_CAPABILITY,
        }:
            payload = document.get("payload")
            return payload if isinstance(payload, dict) else None
        return document


class SubmitExecutionResult:
    def __init__(
        self,
        execution_repository: ExecutionRepository,
        flow_step_repository: FlowStepRepository,
        flow_document_repository: FlowDocumentRepository,
        workflow_engine: AdvanceWorkflow,
        seo_management_repository: SeoAgentManagementRepository | None = None,
        page_execution_service: PageExecutionService | None = None,
    ) -> None:
        self._execution_repository = execution_repository
        self._flow_step_repository = flow_step_repository
        self._flow_document_repository = flow_document_repository
        self._workflow_engine = workflow_engine
        self._seo_management_repository = seo_management_repository
        self._page_execution_service = page_execution_service

    async def execute(
        self,
        execution_id: UUID,
        request: ExecutionResultRequest,
    ) -> ExecutionCompletionResponse | None:
        execution = await self._execution_repository.get(execution_id)
        if execution is None:
            return None
        is_standalone_execution = execution.step_id is None

        result_status = request.status
        result_error = request.error
        if (
            result_status is ExecutionStatus.SUCCEEDED
            and execution.requested_capability == PAGESPEED_CAPABILITY
        ):
            result_error = (
                indexing_denial_reason(request.payload)
                if isinstance(request.payload, dict)
                else "PageSpeed result must be a JSON object"
            )
            if result_error is not None:
                result_status = ExecutionStatus.FAILED
        if (
            result_status is ExecutionStatus.SUCCEEDED
            and execution.requested_capability == INDEXING_CAPABILITY
        ):
            result_error = indexing_result_error(request.payload)
            if result_error is not None:
                result_status = ExecutionStatus.FAILED

        step = None
        step_name = "execution_result"
        if execution.step_id is not None:
            step = await self._flow_step_repository.get(execution.step_id)
            if step is not None:
                step_name = step.step_name.value

        if step_name == SeoFlowStep.WORDPRESS_PAGE_SETUP.value:
            if result_status is ExecutionStatus.SUCCEEDED:
                result_error = _wordpress_page_setup_result_error(request.payload)
                if result_error is None:
                    result_error = await self._sync_wordpress_page_setup(
                        execution,
                        request.payload,
                    )
                if result_error is not None:
                    result_status = ExecutionStatus.FAILED
        elif step_name == SeoFlowStep.WORDPRESS_PUBLISH.value:
            if result_status is ExecutionStatus.SUCCEEDED and request.payload is not True:
                result_status = ExecutionStatus.FAILED
                result_error = "WordPress publish must return payload=true"
            elif result_status is ExecutionStatus.FAILED and request.payload is not False:
                result_error = result_error or "WordPress publish failed"
        elif (
            step_name == SeoFlowStep.SEO_AUDIT.value and result_status is ExecutionStatus.SUCCEEDED
        ):
            result_error = _seo_main_result_validation_error(request.payload)
            if result_error is not None:
                result_status = ExecutionStatus.FAILED

        output_document_id = await self._flow_document_repository.store_document(
            flow_id=execution.flow_id,
            step_name=step_name,
            document_type=result_status.value,
            payload=request.payload,
            execution_id=execution.id,
        )

        if result_status is ExecutionStatus.SUCCEEDED:
            if step_name == SeoFlowStep.SEO_AUDIT.value:
                execution.set_internal_state("page_rewrite_succeeded")
            execution.mark_succeeded_with_output(output_document_id)
        else:
            if step_name == SeoFlowStep.SEO_AUDIT.value:
                execution.set_internal_state("page_rewrite_failed")
            execution.mark_failed(result_error or "Execution failed", output_document_id)

        saved_execution = await self._execution_repository.save(execution)

        completed_step = None
        if step is not None:
            if result_status is ExecutionStatus.SUCCEEDED:
                step.mark_succeeded(output_document_id)
            else:
                step.mark_failed(result_error or "Execution failed", output_document_id)
            completed_step = await self._flow_step_repository.save(step)

        await self._store_pagespeed_artifact(
            saved_execution,
            step,
            request.payload,
            result_status,
            result_error,
        )

        post_indexing_executions: list[ExecutionResponse] = []
        post_indexing_dispatched: list[ExecutionResponse] = []
        post_indexing_pending_dispatch: list[ExecutionResponse] = []
        if completed_step is not None and completed_step.step_name is SeoFlowStep.SUPPORT_POSTS:
            (
                post_indexing_executions,
                post_indexing_dispatched,
                post_indexing_pending_dispatch,
            ) = await self._workflow_engine.create_post_indexing_execution(
                UUID(execution.flow_id),
                completed_step,
            )

        workflow = (
            None
            if is_standalone_execution
            else await self._workflow_engine.execute(UUID(execution.flow_id))
        )
        if workflow is not None:
            workflow.created_executions.extend(post_indexing_executions)
            workflow.dispatched_executions.extend(post_indexing_dispatched)
            workflow.pending_dispatch_executions.extend(post_indexing_pending_dispatch)
        await self._sync_source_queue(workflow)

        return ExecutionCompletionResponse(
            execution=ExecutionResponse.model_validate(saved_execution),
            workflow=workflow,
        )

    async def _sync_wordpress_page_setup(
        self,
        execution: Any,
        payload: dict[str, Any] | bool,
    ) -> str | None:
        if not isinstance(payload, dict) or execution.input_document_id is None:
            return "WordPress page setup input is not available"
        document = await self._flow_document_repository.get_document(
            execution.input_document_id
        )
        input_payload = document.get("payload") if isinstance(document, dict) else None
        if not isinstance(input_payload, dict):
            return "WordPress page setup input is invalid"

        registered_slug = input_payload.get("slug")
        returned_slug = payload.get("slug")
        if returned_slug is not None and returned_slug != registered_slug:
            return "WordPress page setup cannot change the registered slug"
        expected_action = input_payload.get("action")
        if payload.get("action") != expected_action:
            return "WordPress page setup result action does not match the request"

        campaign_page_id = _positive_int_from_payload(input_payload, "campaign_page_id")
        wp_page_id = _positive_int_from_payload(payload, "wp_page_id")
        if campaign_page_id is None or wp_page_id is None:
            return "WordPress page setup requires valid campaign_page_id and wp_page_id"
        if self._seo_management_repository is not None:
            await self._seo_management_repository.update_page_wp_page_id(
                campaign_page_id,
                wp_page_id,
            )
        return None

    async def _store_pagespeed_artifact(
        self,
        execution: Any,
        step: Any,
        payload: Any,
        result_status: ExecutionStatus,
        result_error: str | None,
    ) -> None:
        if (
            self._page_execution_service is None
            or execution.requested_capability != PAGESPEED_CAPABILITY
        ):
            return
        try:
            input_payload = await self._pagespeed_input_payload(execution, step)
            queue_execution_id = (
                _positive_int_from_payload(payload, "queue_execution_id")
                or _positive_int_from_payload(input_payload, "queue_execution_id")
            )
            if queue_execution_id is None:
                logger.warning(
                    "pagespeed_artifact_queue_id_missing",
                    execution_id=str(execution.id),
                    flow_id=execution.flow_id,
                )
                return

            await self._page_execution_service.store_artifact(
                queue_execution_id,
                "pagespeed.json",
                _pagespeed_artifact_payload(
                    payload,
                    execution=execution,
                    input_payload=input_payload,
                    result_status=result_status,
                    result_error=result_error,
                ),
            )
        except Exception as exc:
            logger.warning(
                "pagespeed_artifact_sync_failed",
                execution_id=str(execution.id),
                flow_id=execution.flow_id,
                error=str(exc),
            )

    async def _pagespeed_input_payload(self, execution: Any, step: Any) -> dict[str, Any]:
        input_document_id = execution.input_document_id
        if input_document_id is None and step is not None:
            input_document_id = step.input_document_id
        if input_document_id is None:
            return {}
        document = await self._flow_document_repository.get_document(input_document_id)
        if not isinstance(document, dict):
            return {}
        payload = document.get("payload")
        return payload if isinstance(payload, dict) else {}

    async def _sync_source_queue(self, workflow: Any) -> None:
        if workflow is None or self._seo_management_repository is None:
            return
        correlation_id = workflow.flow.correlation_id or ""
        prefix = "seo-agent-queue:"
        if not correlation_id.startswith(prefix):
            return
        try:
            queue_execution_id = int(correlation_id.removeprefix(prefix))
            if workflow.flow.status not in {FlowStatus.SUCCEEDED, FlowStatus.FAILED}:
                return

            steps = await self._flow_step_repository.list_by_flow(workflow.flow.id)
            published = any(
                step.step_name is SeoFlowStep.WORDPRESS_PUBLISH
                and step.status is FlowStepStatus.SUCCEEDED
                for step in steps
            )
            if published or workflow.flow.status is FlowStatus.SUCCEEDED:
                await self._seo_management_repository.update_queue_result(
                    queue_execution_id,
                    status="success",
                    result_status="published",
                    error_message=_published_page_warning(steps),
                )
            elif workflow.flow.status is FlowStatus.FAILED:
                failed_step = next(
                    (step for step in steps if step.status is FlowStepStatus.FAILED),
                    None,
                )
                detail = (
                    f"{failed_step.step_name.value}: "
                    f"{failed_step.error_message or 'Execution failed'}"
                    if failed_step is not None
                    else "Orchestrator workflow failed"
                )
                await self._seo_management_repository.update_queue_result(
                    queue_execution_id,
                    status="failed",
                    result_status="failed",
                    error_message=detail,
                )
        except Exception as exc:
            logger.warning(
                "source_queue_status_sync_failed",
                correlation_id=correlation_id,
                error=str(exc),
            )


def _published_page_warning(steps: list[Any]) -> str | None:
    failed_steps = [step for step in steps if step.status is FlowStepStatus.FAILED]
    if not failed_steps:
        return None

    details = "; ".join(
        f"{step.step_name.value}: {step.error_message or 'Execution failed'}"
        for step in failed_steps
    )
    if any(step.step_name is SeoFlowStep.INDEXING for step in failed_steps):
        action = "Verificar el envío y completar manualmente la indexación pendiente."
    elif any(step.step_name is SeoFlowStep.PAGESPEED for step in failed_steps):
        action = "Revisar PageSpeed y la indexabilidad; indexar manualmente si corresponde."
    else:
        action = "Revisar las etapas incompletas."
    return f"Advertencia: la página se publicó, pero {details}. {action}"


def _seo_audit_validation_error(payload: dict[str, Any] | bool) -> str | None:
    if not isinstance(payload, dict):
        return "SEO audit result must be a JSON object"
    required_fields = ("post_bot_payload", "video_bot_payload")
    missing = [field for field in required_fields if field not in payload]
    if missing:
        return f"SEO audit result is missing required fields: {', '.join(missing)}"
    if not isinstance(payload["video_bot_payload"], dict):
        return "SEO audit field video_bot_payload must be a JSON object"

    posts = payload["post_bot_payload"]
    if not isinstance(posts, list):
        return "SEO audit field post_bot_payload must be a JSON array"
    for index, post in enumerate(posts):
        error = _post_payload_validation_error(post, index)
        if error is not None:
            return error
    return None


def _wordpress_page_setup_result_error(payload: dict[str, Any] | bool) -> str | None:
    if not isinstance(payload, dict):
        return "WordPress page setup result must be a JSON object"
    if payload.get("schema_version") != "wordpress.page_setup.result.v1":
        return (
            "WordPress page setup result requires "
            "schema_version=wordpress.page_setup.result.v1"
        )
    if payload.get("ok") is not True:
        return "WordPress page setup result requires ok=true"
    if payload.get("action") not in {"create", "update"}:
        return "WordPress page setup result action must be create or update"
    wp_page_id = payload.get("wp_page_id")
    if (
        not isinstance(wp_page_id, int)
        or isinstance(wp_page_id, bool)
        or wp_page_id <= 0
    ):
        return "WordPress page setup result requires a valid wp_page_id"
    slug = payload.get("slug")
    if slug is not None and (not isinstance(slug, str) or not slug):
        return "WordPress page setup result slug must be a non-empty string"
    return None


def _seo_main_result_validation_error(payload: dict[str, Any] | bool) -> str | None:
    if not isinstance(payload, dict):
        return "SEO main result must be a JSON object"
    # Compatibility with agents that still deliver audit and external payloads
    # together as their terminal result.
    if "post_bot_payload" in payload or "video_bot_payload" in payload:
        return _seo_audit_validation_error(payload)
    rewrite_result = payload.get("rewrite_result", payload)
    if not isinstance(rewrite_result, dict):
        return "SEO rewrite_result must be a JSON object"
    if rewrite_result.get("schema_version") != "seo.rewrite.v1":
        return "SEO rewrite_result schema_version must be seo.rewrite.v1"
    if rewrite_result.get("ok") is not True:
        return "SEO rewrite_result must return ok=true"
    campaign_page_id = rewrite_result.get("campaign_page_id")
    if not isinstance(campaign_page_id, int) or campaign_page_id <= 0:
        return "SEO rewrite_result requires a valid campaign_page_id"
    stage = rewrite_result.get("stage")
    if not isinstance(stage, str) or not stage:
        return "SEO rewrite_result requires a stage"
    page_update = rewrite_result.get("page_update")
    if not isinstance(page_update, dict):
        return "SEO rewrite_result requires page_update"
    elementor_data = page_update.get("updated_elementor_data")
    if not _has_content(elementor_data):
        return "SEO rewrite_result requires non-empty page_update.updated_elementor_data"
    if "pending_insertions" not in rewrite_result:
        return "SEO rewrite_result requires pending_insertions"
    return None


def _post_payload_validation_error(post: Any, index: int) -> str | None:
    field_prefix = f"post_bot_payload[{index}]"
    if not isinstance(post, dict):
        return f"{field_prefix} must be a JSON object"

    expected_fields = set(POST_BOT_PAYLOAD_FIELDS)
    missing = sorted(expected_fields - set(post))
    if missing:
        return f"{field_prefix} is missing required fields: {', '.join(missing)}"
    for field, expected_type in POST_BOT_PAYLOAD_FIELDS.items():
        if not isinstance(post[field], expected_type):
            return f"{field_prefix}.{field} has an invalid type"

    campaign_url = urlsplit(post["campaign_id"])
    if (
        campaign_url.scheme not in {"http", "https"}
        or not campaign_url.netloc
        or campaign_url.path not in {"", "/"}
        or campaign_url.query
        or campaign_url.fragment
    ):
        return f"{field_prefix}.campaign_id must be the main domain URL"
    return None


def _has_content(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list)):
        return bool(value)
    return value is not None


def _positive_int_from_payload(payload: Any, key: str) -> int | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    if value is None and isinstance(payload.get("payload"), dict):
        value = payload["payload"].get(key)
    if isinstance(value, bool):
        return None
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def _first_text_from_payload(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _pagespeed_artifact_payload(
    payload: Any,
    *,
    execution: Any,
    input_payload: dict[str, Any],
    result_status: ExecutionStatus,
    result_error: str | None,
) -> dict[str, Any]:
    artifact = dict(payload) if isinstance(payload, dict) else {"payload": payload}
    artifact.setdefault("stage", SeoFlowStep.PAGESPEED.value)
    artifact.setdefault("schema_version", "pagespeed.result.v1")
    artifact.setdefault("flow_id", execution.flow_id)
    artifact.setdefault("execution_id", str(execution.id))
    artifact["orchestrator_status"] = result_status.value
    if result_error:
        artifact["orchestrator_error"] = result_error

    page_url = _first_text_from_payload(
        artifact,
        "page_url",
        "url",
    ) or _first_text_from_payload(
        input_payload,
        "page_url",
        "url",
    )
    if page_url and "page_url" not in artifact and "url" not in artifact:
        artifact["page_url"] = page_url

    campaign_page_id = (
        _positive_int_from_payload(artifact, "campaign_page_id")
        or _positive_int_from_payload(input_payload, "campaign_page_id")
    )
    if campaign_page_id is not None:
        artifact.setdefault("campaign_page_id", campaign_page_id)
    return artifact
