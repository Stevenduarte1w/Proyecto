from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from orchestrator.application.dtos import (
    ExecutionResponse,
    FlowResponse,
    FlowStepResponse,
    WorkflowAdvanceResponse,
)
from orchestrator.application.use_cases.dispatch_execution import DispatchExecution
from orchestrator.domain.entities import (
    Execution,
    ExecutionStatus,
    Flow,
    FlowStatus,
    FlowStep,
    FlowStepStatus,
    SeoFlowStep,
)
from orchestrator.domain.indexing import (
    INDEXING_CAPABILITY,
    INDEXING_INPUT_SCHEMA,
    INDEXING_STAGE,
)
from orchestrator.domain.ports import (
    ExecutionRepository,
    FlowDocumentRepository,
    FlowRepository,
    FlowStepRepository,
)
from orchestrator.domain.workflow import SEO_STEP_DEFINITIONS

EXTERNAL_STEPS = {SeoFlowStep.SUPPORT_POSTS, SeoFlowStep.VIDEO_REQUEST}
SKIPPABLE_STEPS = EXTERNAL_STEPS | {SeoFlowStep.WORDPRESS_PAGE_SETUP}
EXTERNAL_PAYLOAD_FIELDS = {
    SeoFlowStep.SUPPORT_POSTS: "post_bot_payload",
    SeoFlowStep.VIDEO_REQUEST: "video_bot_payload",
}
VIDEO_REQUEST_TIMEOUT = timedelta(minutes=90)
SUPPORT_POST_MODES = {"auto", "state_defined", "legacy_two", "none"}


class AdvanceWorkflow:
    def __init__(
        self,
        flow_repository: FlowRepository,
        flow_step_repository: FlowStepRepository,
        execution_repository: ExecutionRepository,
        flow_document_repository: FlowDocumentRepository,
        dispatcher: DispatchExecution | None = None,
    ) -> None:
        self._flow_repository = flow_repository
        self._flow_step_repository = flow_step_repository
        self._execution_repository = execution_repository
        self._flow_document_repository = flow_document_repository
        self._dispatcher = dispatcher

    async def execute(self, flow_id: UUID) -> WorkflowAdvanceResponse | None:
        flow = await self._flow_repository.get(flow_id)
        if flow is None:
            return None

        steps = await self._flow_step_repository.list_by_flow(flow_id)
        steps_by_name = {step.step_name: step for step in steps}
        await self._expire_stale_video_request(flow, steps_by_name)

        if any(
            step.status is FlowStepStatus.FAILED and step.step_name not in EXTERNAL_STEPS
            for step in steps
        ):
            flow.mark_failed()
            saved_flow = await self._flow_repository.save(flow)
            return WorkflowAdvanceResponse(
                flow=FlowResponse(**asdict(saved_flow)),
                completed=False,
            )

        if all(_step_allows_flow_completion(step) for step in steps):
            flow.mark_succeeded()
            saved_flow = await self._flow_repository.save(flow)
            return WorkflowAdvanceResponse(
                flow=FlowResponse(**asdict(saved_flow)),
                completed=True,
            )

        source_seo_bot_id = await self._source_seo_main_bot_id(steps_by_name)
        preferred_seo_bot_id = await self._preferred_seo_bot_id(flow)
        created_executions: list[Execution] = []
        created_execution_steps: dict[UUID, SeoFlowStep] = {}
        waiting_approval_step: FlowStep | None = None

        for step in steps:
            if step.status is not FlowStepStatus.PENDING:
                continue

            definition = SEO_STEP_DEFINITIONS[step.step_name]
            if not _dependencies_succeeded(definition.depends_on, steps_by_name):
                continue

            if definition.manual_gate:
                step.mark_waiting_approval()
                waiting_approval_step = await self._flow_step_repository.save(step)
                flow.mark_waiting_approval()
                break

            if step.requested_capability is None:
                step.mark_failed("Step has no requested capability")
                await self._flow_step_repository.save(step)
                flow.mark_failed()
                break

            input_document_id = await self._create_step_input_document(flow, step, steps_by_name)
            step.input_document_id = input_document_id
            execution = Execution(
                flow_id=str(flow.id),
                step_id=step.id,
                requested_capability=step.requested_capability,
                status=ExecutionStatus.PENDING,
                bot_id=_preferred_bot_id_for_step(
                    step.requested_capability,
                    step.step_name,
                    source_seo_bot_id,
                    preferred_seo_bot_id,
                ),
                input_document_id=input_document_id,
            )
            saved_execution = await self._execution_repository.save(execution)
            step.assign_execution(saved_execution.id)
            await self._flow_step_repository.save(step)
            if saved_execution.id == execution.id:
                created_executions.append(saved_execution)
                created_execution_steps[saved_execution.id] = step.step_name

        terminal_or_blocked = {
            FlowStatus.WAITING_APPROVAL,
            FlowStatus.FAILED,
            FlowStatus.SUCCEEDED,
        }
        if flow.status not in terminal_or_blocked:
            active_step = _first_active_step(steps)
            if active_step is not None:
                flow.current_step = active_step.step_name
            if any(
                step.step_name in EXTERNAL_STEPS
                for step in steps
                if step.status is FlowStepStatus.QUEUED
            ):
                flow.mark_waiting_external()
            else:
                flow.mark_in_progress()

        saved_flow = await self._flow_repository.save(flow)
        dispatched_executions: list[ExecutionResponse] = []
        pending_dispatch_executions: list[ExecutionResponse] = []
        if self._dispatcher is not None:
            for execution in created_executions:
                dispatched = await self._dispatcher.dispatch_if_bot_available(
                    execution.id,
                    preferred_bot_id=_preferred_bot_id_for_step(
                        execution.requested_capability,
                        created_execution_steps.get(execution.id),
                        source_seo_bot_id,
                        preferred_seo_bot_id,
                    ),
                )
                if dispatched.status is ExecutionStatus.QUEUED:
                    dispatched_executions.append(dispatched)
                else:
                    pending_dispatch_executions.append(dispatched)

        refreshed_steps = await self._flow_step_repository.list_by_flow(flow.id)
        waiting_approval_step = waiting_approval_step or next(
            (step for step in refreshed_steps if step.status is FlowStepStatus.WAITING_APPROVAL),
            None,
        )

        return WorkflowAdvanceResponse(
            flow=FlowResponse(**asdict(saved_flow)),
            created_executions=[
                ExecutionResponse.model_validate(execution) for execution in created_executions
            ],
            dispatched_executions=dispatched_executions,
            pending_dispatch_executions=pending_dispatch_executions,
            waiting_approval_step=FlowStepResponse(**asdict(waiting_approval_step))
            if waiting_approval_step
            else None,
            completed=saved_flow.status is FlowStatus.SUCCEEDED,
        )

    async def process_external_payloads_checkpoint(
        self,
        flow_id: UUID,
        source_execution_id: UUID,
        checkpoint_payload: dict[str, Any],
    ) -> WorkflowAdvanceResponse | None:
        flow = await self._flow_repository.get(flow_id)
        if flow is None:
            return None

        steps = await self._flow_step_repository.list_by_flow(flow_id)
        steps_by_name = {step.step_name: step for step in steps}
        source_step = steps_by_name.get(SeoFlowStep.SEO_AUDIT)
        if source_step is None or source_step.execution_id != source_execution_id:
            raise RuntimeError("Checkpoint does not belong to the SEO audit execution")

        created_executions: list[Execution] = []
        for step_name in (SeoFlowStep.SUPPORT_POSTS, SeoFlowStep.VIDEO_REQUEST):
            step = steps_by_name.get(step_name)
            if step is None or step.status is not FlowStepStatus.PENDING:
                continue
            payload_field = EXTERNAL_PAYLOAD_FIELDS[step_name]
            external_payload = checkpoint_payload[payload_field]
            if step_name is SeoFlowStep.SUPPORT_POSTS:
                external_payload = _post_bot_payload_for_mode(checkpoint_payload)
                no_posts_output = _support_posts_output_without_create(checkpoint_payload)
                if no_posts_output is not None:
                    output_document_id = await self._flow_document_repository.store_document(
                        flow_id=str(flow.id),
                        step_name=step.step_name.value,
                        document_type=no_posts_output["document_type"],
                        payload=no_posts_output["payload"],
                        correlation_id=flow.correlation_id,
                    )
                    if no_posts_output["status"] == "succeeded":
                        step.mark_succeeded(output_document_id)
                    else:
                        step.mark_skipped(output_document_id)
                    await self._flow_step_repository.save(step)
                    continue
            if _external_payload_is_skipped(step_name, external_payload):
                skipped_payload = (
                    {"posts": [], "published_posts": [], "skipped": True}
                    if step_name is SeoFlowStep.SUPPORT_POSTS
                    else {"skipped": True}
                )
                output_document_id = await self._flow_document_repository.store_document(
                    flow_id=str(flow.id),
                    step_name=step.step_name.value,
                    document_type="skipped",
                    payload=skipped_payload,
                    correlation_id=flow.correlation_id,
                )
                step.mark_skipped(output_document_id)
                await self._flow_step_repository.save(step)
                continue
            if step.requested_capability is None:
                raise RuntimeError(f"{step_name.value} has no requested capability")

            input_document_id = await self._create_external_checkpoint_input_document(
                flow=flow,
                step=step,
                source_execution_id=source_execution_id,
                external_payload=external_payload,
            )
            step.input_document_id = input_document_id
            execution = Execution(
                flow_id=str(flow.id),
                step_id=step.id,
                requested_capability=step.requested_capability,
                status=ExecutionStatus.PENDING,
                input_document_id=input_document_id,
            )
            saved_execution = await self._execution_repository.save(execution)
            step.assign_execution(saved_execution.id)
            await self._flow_step_repository.save(step)
            if saved_execution.id == execution.id:
                created_executions.append(saved_execution)

        if created_executions:
            flow.mark_waiting_external()
        else:
            flow.current_step = SeoFlowStep.SEO_AUDIT
            flow.mark_in_progress()
        saved_flow = await self._flow_repository.save(flow)
        dispatched_executions: list[ExecutionResponse] = []
        pending_dispatch_executions: list[ExecutionResponse] = []
        if self._dispatcher is not None:
            for execution in created_executions:
                dispatched = await self._dispatcher.dispatch_if_bot_available(execution.id)
                if dispatched.status is ExecutionStatus.QUEUED:
                    dispatched_executions.append(dispatched)
                else:
                    pending_dispatch_executions.append(dispatched)

        return WorkflowAdvanceResponse(
            flow=FlowResponse(**asdict(saved_flow)),
            created_executions=[
                ExecutionResponse.model_validate(execution) for execution in created_executions
            ],
            dispatched_executions=dispatched_executions,
            pending_dispatch_executions=pending_dispatch_executions,
        )

    async def create_post_indexing_execution(
        self,
        flow_id: UUID,
        posts_step: FlowStep,
    ) -> tuple[list[ExecutionResponse], list[ExecutionResponse], list[ExecutionResponse]]:
        flow = await self._flow_repository.get(flow_id)
        if flow is None or posts_step.step_name is not SeoFlowStep.SUPPORT_POSTS:
            return [], [], []

        posts_result = await self._get_posts_result(posts_step)
        post_urls = [
            post["url"]
            for post in posts_result["published_posts"]
            if isinstance(post, dict) and isinstance(post.get("url"), str)
        ]
        urls_to_index = list(dict.fromkeys(post_urls))
        if not urls_to_index:
            return [], [], []

        input_document_id = await self._store_indexing_input_document(
            flow=flow,
            step_name=SeoFlowStep.SUPPORT_POSTS,
            urls_to_index=urls_to_index,
            source="support_posts_result",
        )
        execution = Execution(
            flow_id=str(flow.id),
            requested_capability=INDEXING_CAPABILITY,
            status=ExecutionStatus.PENDING,
            input_document_id=input_document_id,
        )
        saved_execution = await self._execution_repository.save(execution)

        created_executions = [ExecutionResponse.model_validate(saved_execution)]
        dispatched_executions: list[ExecutionResponse] = []
        pending_dispatch_executions: list[ExecutionResponse] = []
        if self._dispatcher is not None:
            dispatched = await self._dispatcher.dispatch_if_bot_available(saved_execution.id)
            if dispatched.status is ExecutionStatus.QUEUED:
                dispatched_executions.append(dispatched)
            else:
                pending_dispatch_executions.append(dispatched)
        return created_executions, dispatched_executions, pending_dispatch_executions

    async def _create_external_checkpoint_input_document(
        self,
        flow: Flow,
        step: FlowStep,
        source_execution_id: UUID,
        external_payload: Any,
    ) -> str:
        queue_execution_id, campaign_page_id = await self._get_source_context(flow)
        payload = {
            "stage": step.step_name.value,
            "queue_execution_id": queue_execution_id,
            "campaign_page_id": campaign_page_id,
            "page_url": flow.page_url,
            "log_url": f"/api/v1/page-executions/{queue_execution_id}/log",
            "log_method": "PUT",
            "artifacts_url": f"/api/v1/page-executions/{queue_execution_id}/artifacts",
            "flow_id": str(flow.id),
            "source_execution_id": str(source_execution_id),
            "payload": external_payload,
        }
        return await self._flow_document_repository.store_document(
            flow_id=str(flow.id),
            step_name=step.step_name.value,
            document_type="workflow_step_input",
            payload=payload,
            correlation_id=flow.correlation_id,
        )

    async def _create_step_input_document(
        self,
        flow: Flow,
        step: FlowStep,
        steps_by_name: dict[SeoFlowStep, FlowStep],
    ) -> str:
        definition = SEO_STEP_DEFINITIONS[step.step_name]
        queue_execution_id, campaign_page_id = await self._get_source_context(flow)
        dependency_outputs = [
            {
                "step_name": dependency.value,
                "step_id": str(steps_by_name[dependency].id),
                "output_document_id": steps_by_name[dependency].output_document_id,
            }
            for dependency in definition.depends_on
        ]
        payload: dict[str, Any] = {
            "stage": step.step_name.value,
            "queue_execution_id": queue_execution_id,
            "campaign_page_id": campaign_page_id,
            "page_url": flow.page_url,
            "log_url": f"/api/v1/page-executions/{queue_execution_id}/log",
            "log_method": "PUT",
            "artifacts_url": (f"/api/v1/page-executions/{queue_execution_id}/artifacts"),
        }
        if step.step_name is SeoFlowStep.SEO_AUDIT:
            source_payload = await self._get_initial_payload(flow)
            payload.update(
                {
                    "workflow_stage": SeoFlowStep.SEO_AUDIT.value,
                    "flow_type": flow.flow_type,
                    "campaign": flow.campaign,
                    "commercial_objective": flow.commercial_objective,
                    "support_posts": source_payload.get(
                        "support_posts",
                        {"mode": "auto"},
                    ),
                }
            )
            setup_step = steps_by_name.get(SeoFlowStep.WORDPRESS_PAGE_SETUP)
            if setup_step is not None and setup_step.output_document_id is not None:
                payload["page_setup_result"] = await self._get_step_result_payload(
                    setup_step
                )
        elif step.step_name in EXTERNAL_PAYLOAD_FIELDS:
            source_step = steps_by_name[SeoFlowStep.SEO_AUDIT]
            payload.update(
                {
                    "flow_id": str(flow.id),
                    "source_execution_id": str(source_step.execution_id),
                    "payload": await self._get_external_bot_payload(
                        source_step,
                        EXTERNAL_PAYLOAD_FIELDS[step.step_name],
                    ),
                }
            )
        elif step.step_name is SeoFlowStep.WORDPRESS_PUBLISH:
            rewrite_step = steps_by_name[SeoFlowStep.SEO_AUDIT]
            payload.update(
                {
                    "flow_id": str(flow.id),
                    "source_rewrite_execution_id": str(rewrite_step.execution_id),
                    "rewrite_result": await self._get_rewrite_result(rewrite_step),
                    "posts_result": await self._get_posts_result(
                        steps_by_name[SeoFlowStep.SUPPORT_POSTS]
                    ),
                    "video_result": await self._get_step_result_payload(
                        steps_by_name[SeoFlowStep.VIDEO_REQUEST]
                    ),
                }
            )
        elif step.step_name is SeoFlowStep.PAGESPEED:
            payload.update(
                {
                    "flow_id": str(flow.id),
                    "strategy": ["mobile", "desktop"],
                }
            )
        elif step.step_name is SeoFlowStep.INDEXING:
            return await self._store_indexing_input_document(
                flow=flow,
                step_name=step.step_name,
                urls_to_index=[flow.page_url],
                source="final_page_indexing",
            )
        else:
            payload.update(
                {
                    "flow": {
                        "id": str(flow.id),
                        "flow_type": flow.flow_type,
                        "page_url": flow.page_url,
                        "campaign": flow.campaign,
                        "commercial_objective": flow.commercial_objective,
                        "initial_document_id": flow.initial_document_id,
                        "correlation_id": flow.correlation_id,
                    },
                    "step": {
                        "id": str(step.id),
                        "name": step.step_name.value,
                        "position": step.position,
                        "requested_capability": step.requested_capability,
                    },
                    "dependencies": dependency_outputs,
                }
            )
        return await self._flow_document_repository.store_document(
            flow_id=str(flow.id),
            step_name=step.step_name.value,
            document_type="workflow_step_input",
            payload=payload,
            correlation_id=flow.correlation_id,
        )

    async def _store_indexing_input_document(
        self,
        *,
        flow: Flow,
        step_name: SeoFlowStep,
        urls_to_index: list[str],
        source: str,
    ) -> str:
        queue_execution_id, campaign_page_id = await self._get_source_context(flow)
        payload = {
            "stage": INDEXING_STAGE,
            "queue_execution_id": queue_execution_id,
            "campaign_page_id": campaign_page_id,
            "page_url": flow.page_url,
            "flow_id": str(flow.id),
            "source": source,
            "payload": {
                "schema_version": INDEXING_INPUT_SCHEMA,
                "page_url": flow.page_url,
                "urls_to_index": urls_to_index,
                "providers": {
                    "google_search_console": True,
                    "twoindex_ninja": True,
                },
            },
        }
        return await self._flow_document_repository.store_document(
            flow_id=str(flow.id),
            step_name=step_name.value,
            document_type="workflow_step_input",
            payload=payload,
            correlation_id=flow.correlation_id,
        )

    async def _source_seo_main_bot_id(
        self,
        steps_by_name: dict[SeoFlowStep, FlowStep],
    ) -> UUID | None:
        source_step = steps_by_name.get(SeoFlowStep.SEO_AUDIT)
        if source_step is None or source_step.execution_id is None:
            return None
        source_execution = await self._execution_repository.get(source_step.execution_id)
        if (
            source_execution is None
            or source_execution.requested_capability != "seo.main"
        ):
            return None
        return source_execution.bot_id

    async def _expire_stale_video_request(
        self,
        flow: Flow,
        steps_by_name: dict[SeoFlowStep, FlowStep],
    ) -> None:
        step = steps_by_name.get(SeoFlowStep.VIDEO_REQUEST)
        if step is None or step.execution_id is None:
            return
        if step.status not in {
            FlowStepStatus.QUEUED,
            FlowStepStatus.RUNNING,
        }:
            return

        execution = await self._execution_repository.get(step.execution_id)
        if execution is None or execution.status not in {
            ExecutionStatus.PENDING,
            ExecutionStatus.QUEUED,
            ExecutionStatus.RUNNING,
        }:
            return

        timeout_started_at = execution.started_at or execution.created_at
        if datetime.now(UTC) - _ensure_utc(timeout_started_at) < VIDEO_REQUEST_TIMEOUT:
            return

        reason = "Video bot did not respond within 90 minutes"
        output_document_id = await self._flow_document_repository.store_document(
            flow_id=str(flow.id),
            step_name=SeoFlowStep.VIDEO_REQUEST.value,
            document_type="failed",
            payload={
                "error": reason,
                "timeout_seconds": int(VIDEO_REQUEST_TIMEOUT.total_seconds()),
            },
            execution_id=execution.id,
            correlation_id=flow.correlation_id,
        )
        execution.mark_failed(reason, output_document_id)
        await self._execution_repository.save(execution)
        step.mark_failed(reason, output_document_id)
        await self._flow_step_repository.save(step)

    async def _get_external_bot_payload(
        self,
        source_step: FlowStep,
        payload_field: str,
    ) -> Any:
        if source_step.execution_id is None or source_step.output_document_id is None:
            raise RuntimeError("SEO audit result is not available")
        document = await self._flow_document_repository.get_document(source_step.output_document_id)
        if document is None:
            raise RuntimeError("SEO audit result document was not found")
        audit_result = document.get("payload")
        if not isinstance(audit_result, dict):
            raise RuntimeError("SEO audit result payload is invalid")
        external_payload = audit_result.get(payload_field)
        if payload_field == "post_bot_payload":
            if not isinstance(external_payload, list):
                raise RuntimeError("SEO audit result requires post_bot_payload")
            return external_payload
        if not isinstance(external_payload, dict):
            raise RuntimeError(f"SEO audit result requires {payload_field}")
        return external_payload

    async def _get_posts_result(self, posts_step: FlowStep) -> dict[str, Any]:
        result = await self._get_step_result_payload(posts_step)
        posts = result.get("posts")
        published_posts = _published_posts(posts)
        posts_result: dict[str, Any] = {"published_posts": published_posts}
        existing_posts = result.get("existing_posts")
        if isinstance(existing_posts, list):
            posts_result["existing_posts"] = _published_posts(existing_posts)
        support_posts_required = result.get("support_posts_required")
        if isinstance(support_posts_required, int) and not isinstance(
            support_posts_required,
            bool,
        ):
            posts_result["support_posts_required"] = support_posts_required
        support_posts_plan = result.get("support_posts_plan")
        if isinstance(support_posts_plan, dict):
            posts_result["support_posts_plan"] = support_posts_plan
        return posts_result

    async def _get_step_result_payload(self, step: FlowStep) -> dict[str, Any]:
        if step.output_document_id is None:
            return {}
        document = await self._flow_document_repository.get_document(step.output_document_id)
        if document is None:
            raise RuntimeError(f"{step.step_name.value} result document was not found")
        result = document.get("payload")
        return result if isinstance(result, dict) else {}

    async def _get_rewrite_result(self, rewrite_step: FlowStep) -> dict[str, Any]:
        terminal_result = await self._get_step_result_payload(rewrite_step)
        nested_rewrite_result = terminal_result.get("rewrite_result")
        if isinstance(nested_rewrite_result, dict):
            return nested_rewrite_result
        return terminal_result

    async def _get_source_context(self, flow: Flow) -> tuple[int, int]:
        payload = await self._get_initial_payload(flow)

        nested_payload = payload.get("payload")
        queue_execution_id = payload.get("queue_execution_id")
        if queue_execution_id is None and isinstance(nested_payload, dict):
            queue_execution_id = nested_payload.get("queue_execution_id")

        campaign_page_id = payload.get("campaign_page_id")
        if campaign_page_id is None and isinstance(nested_payload, dict):
            campaign_page = nested_payload.get("campaign_page")
            if isinstance(campaign_page, dict):
                campaign_page_id = campaign_page.get("id")

        if not isinstance(queue_execution_id, int) or queue_execution_id <= 0:
            raise RuntimeError("Flow input requires a valid queue_execution_id")
        if not isinstance(campaign_page_id, int) or campaign_page_id <= 0:
            raise RuntimeError("Flow input requires a valid campaign_page_id")
        return queue_execution_id, campaign_page_id

    async def _get_initial_payload(self, flow: Flow) -> dict[str, Any]:
        if flow.initial_document_id is None:
            raise RuntimeError("Flow has no initial document")
        document = await self._flow_document_repository.get_document(flow.initial_document_id)
        if document is None:
            raise RuntimeError("Flow initial document was not found")
        payload = document.get("payload")
        if not isinstance(payload, dict):
            raise RuntimeError("Flow initial payload is invalid")
        return payload

    async def _preferred_seo_bot_id(self, flow: Flow) -> UUID | None:
        if flow.initial_document_id is None:
            return None
        document = await self._flow_document_repository.get_document(flow.initial_document_id)
        if not isinstance(document, dict) or not isinstance(document.get("payload"), dict):
            return None
        payload = document["payload"]
        raw = payload.get("preferred_seo_bot_id")
        if not isinstance(raw, str) or not raw:
            return None
        try:
            return UUID(raw)
        except ValueError:
            return None


def _dependencies_succeeded(
    dependencies: tuple[SeoFlowStep, ...],
    steps_by_name: dict[SeoFlowStep, FlowStep],
) -> bool:
    return all(
        steps_by_name[dependency].status is FlowStepStatus.SUCCEEDED
        or (
            dependency in SKIPPABLE_STEPS
            and steps_by_name[dependency].status is FlowStepStatus.SKIPPED
        )
        or (
            dependency in EXTERNAL_STEPS
            and steps_by_name[dependency].status is FlowStepStatus.FAILED
        )
        for dependency in dependencies
    )


def _preferred_bot_id_for_step(
    requested_capability: str | None,
    step_name: SeoFlowStep | None,
    source_seo_bot_id: UUID | None,
    preferred_seo_bot_id: UUID | None,
) -> UUID | None:
    if requested_capability != "seo.main":
        return None
    if step_name is SeoFlowStep.SEO_AUDIT:
        return preferred_seo_bot_id
    if step_name is None:
        return None
    return source_seo_bot_id


def _step_allows_flow_completion(step: FlowStep) -> bool:
    return step.status is FlowStepStatus.SUCCEEDED or (
        step.step_name in SKIPPABLE_STEPS
        and step.status is FlowStepStatus.SKIPPED
    ) or (
        step.step_name in EXTERNAL_STEPS and step.status is FlowStepStatus.FAILED
    )


def _first_active_step(steps: list[FlowStep]) -> FlowStep | None:
    active_statuses = {
        FlowStepStatus.QUEUED,
        FlowStepStatus.RUNNING,
        FlowStepStatus.WAITING_APPROVAL,
    }
    return next((step for step in steps if step.status in active_statuses), None)


def _external_payload_is_skipped(step_name: SeoFlowStep, payload: Any) -> bool:
    if step_name is SeoFlowStep.SUPPORT_POSTS:
        return isinstance(payload, list) and not payload
    if not isinstance(payload, dict) or not payload:
        return True
    if payload.get("skipped") is True or payload.get("skip") is True:
        return True
    if payload.get("omitted") is True:
        return True
    if payload.get("should_generate") is False or payload.get("generate") is False:
        return True
    status = payload.get("status")
    if isinstance(status, str) and status.lower() in {"skipped", "omitted"}:
        return True
    required_text_fields = ("schema_version", "stage", "flow_id", "source_execution_id")
    if any(
        not isinstance(payload.get(field), str) or not payload[field]
        for field in required_text_fields
    ):
        return True
    campaign_page_id = payload.get("campaign_page_id")
    if not isinstance(campaign_page_id, int) or campaign_page_id <= 0:
        return True
    page_url = (
        payload.get("page_url") or payload.get("source_page_url") or payload.get("target_page")
    )
    if not isinstance(page_url, str) or not page_url:
        return True
    title_or_package = payload.get("title") or payload.get("video_package")
    return not isinstance(title_or_package, (str, dict)) or not title_or_package


def _post_bot_payload_for_mode(checkpoint_payload: dict[str, Any]) -> list[Any]:
    posts = checkpoint_payload.get("post_bot_payload")
    if not isinstance(posts, list):
        return []
    if _support_posts_mode_from_checkpoint(checkpoint_payload) == "legacy_two":
        return posts[:2]
    return posts


def _support_posts_output_without_create(
    checkpoint_payload: dict[str, Any],
) -> dict[str, Any] | None:
    posts = checkpoint_payload.get("post_bot_payload")
    if isinstance(posts, list) and posts:
        return None

    support_posts_plan = checkpoint_payload.get("support_posts_plan")
    plan = support_posts_plan if isinstance(support_posts_plan, dict) else {}
    existing_posts = plan.get("existing_posts")
    if isinstance(existing_posts, list) and existing_posts:
        published_posts = _published_posts(existing_posts)
        return {
            "status": "succeeded",
            "document_type": "succeeded",
            "payload": {
                "posts": published_posts,
                "published_posts": published_posts,
                "existing_posts": published_posts,
                "support_posts_plan": plan,
                "skipped_create": True,
            },
        }

    if _support_posts_mode_from_checkpoint(checkpoint_payload) == "none":
        return {
            "status": "skipped",
            "document_type": "skipped",
            "payload": {
                "posts": [],
                "published_posts": [],
                "support_posts_required": 0,
                "support_posts_plan": plan,
                "skipped": True,
            },
        }
    return None


def _support_posts_mode_from_checkpoint(checkpoint_payload: dict[str, Any]) -> str | None:
    support_posts = checkpoint_payload.get("support_posts")
    if isinstance(support_posts, dict) and support_posts.get("mode") in SUPPORT_POST_MODES:
        return str(support_posts["mode"])
    support_posts_plan = checkpoint_payload.get("support_posts_plan")
    if isinstance(support_posts_plan, dict):
        mode = support_posts_plan.get("mode") or support_posts_plan.get("requested_mode")
        if mode in SUPPORT_POST_MODES:
            return str(mode)
    return None


def _published_posts(posts: Any) -> list[dict[str, str]]:
    published_posts: list[dict[str, str]] = []
    if not isinstance(posts, list):
        return published_posts
    for post in posts:
        if not isinstance(post, dict):
            continue
        url = post.get("url") or post.get("post_url") or post.get("link")
        if not isinstance(url, str) or not url:
            continue
        status = post.get("status", "published")
        if isinstance(status, str) and status not in {"published", "existing"}:
            continue
        title = post.get("title") or post.get("post_title") or ""
        published_posts.append(
            {
                "title": title if isinstance(title, str) else "",
                "url": url,
                "status": "published",
            }
        )
    return published_posts


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
