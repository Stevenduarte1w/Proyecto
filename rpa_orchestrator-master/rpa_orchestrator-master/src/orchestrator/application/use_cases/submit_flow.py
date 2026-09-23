from __future__ import annotations

from dataclasses import asdict
from typing import Any

from orchestrator.application.dtos import (
    ExecutionResponse,
    FlowResponse,
    FlowStepResponse,
    FlowSubmitRequest,
    FlowSubmitResponse,
    WordpressPageSetupRequest,
)
from orchestrator.application.use_cases.dispatch_execution import DispatchExecution
from orchestrator.domain.entities import (
    SEO_WORKFLOW_STEPS,
    Execution,
    ExecutionStatus,
    Flow,
    FlowStep,
    SeoFlowStep,
)
from orchestrator.domain.ports import (
    ExecutionRepository,
    FlowDocumentRepository,
    FlowRepository,
    FlowStepRepository,
)
from orchestrator.domain.workflow import capability_for_step

SUPPORT_POST_MODES = {"auto", "state_defined", "legacy_two", "none"}


class SubmitFlow:
    def __init__(
        self,
        flow_document_repository: FlowDocumentRepository,
        flow_repository: FlowRepository,
        flow_step_repository: FlowStepRepository,
        execution_repository: ExecutionRepository,
        dispatcher: DispatchExecution | None = None,
    ) -> None:
        self._flow_document_repository = flow_document_repository
        self._flow_repository = flow_repository
        self._flow_step_repository = flow_step_repository
        self._execution_repository = execution_repository
        self._dispatcher = dispatcher

    async def execute(self, request: FlowSubmitRequest) -> FlowSubmitResponse:
        support_posts_mode = _support_posts_mode(request.payload)
        page_setup = request.page_setup or WordpressPageSetupRequest(
            action="skip",
            slug=_slug_from_page_url(str(request.page_url)),
        )
        initial_step = (
            SeoFlowStep.SEO_AUDIT
            if page_setup.action == "skip"
            else SeoFlowStep.WORDPRESS_PAGE_SETUP
        )
        flow = Flow(
            flow_type=request.flow_type,
            page_url=str(request.page_url),
            campaign=request.campaign,
            commercial_objective=request.commercial_objective,
            correlation_id=request.correlation_id,
            current_step=initial_step,
        )
        initial_payload: dict[str, Any] = {
            "stage": initial_step.value,
            "workflow_stage": initial_step.value,
            "queue_execution_id": request.queue_execution_id,
            "campaign_page_id": request.campaign_page_id,
            "page_url": str(request.page_url),
            "log_url": f"/api/v1/page-executions/{request.queue_execution_id}/log",
            "log_method": "PUT",
            "artifacts_url": (
                f"/api/v1/page-executions/{request.queue_execution_id}/artifacts"
            ),
            "flow_type": request.flow_type,
            "campaign": request.campaign,
            "commercial_objective": request.commercial_objective,
            "support_posts": {"mode": support_posts_mode},
            "preferred_seo_bot_id": (
                str(request.preferred_bot_id) if request.preferred_bot_id else None
            ),
        }
        if initial_step is SeoFlowStep.WORDPRESS_PAGE_SETUP:
            initial_payload.update(
                {
                    "schema_version": "wordpress.page_setup.input.v1",
                    "page_setup": page_setup.model_dump(mode="json"),
                    "action": page_setup.action,
                    "slug": page_setup.slug,
                    "wp_page_id": page_setup.wp_page_id,
                    "campaign_id": page_setup.campaign_id,
                }
            )

        initial_document_id = await self._flow_document_repository.store_document(
            flow_id=str(flow.id),
            step_name="initial_request",
            document_type="flow_input",
            payload=initial_payload,
            correlation_id=request.correlation_id,
        )
        flow.initial_document_id = initial_document_id
        saved_flow = await self._flow_repository.save(flow)

        steps = [
            FlowStep(
                flow_id=saved_flow.id,
                step_name=step_name,
                position=position,
                input_document_id=initial_document_id if step_name is initial_step else None,
                requested_capability=capability_for_step(step_name, request.requested_capability),
            )
            for position, step_name in enumerate(SEO_WORKFLOW_STEPS, start=1)
        ]
        saved_steps = await self._flow_step_repository.save_many(steps)
        setup_step = next(
            step
            for step in saved_steps
            if step.step_name is SeoFlowStep.WORDPRESS_PAGE_SETUP
        )
        if page_setup.action == "skip":
            setup_step.mark_skipped()
            await self._flow_step_repository.save(setup_step)
        first_step = next(step for step in saved_steps if step.step_name is initial_step)

        execution = Execution(
            flow_id=str(saved_flow.id),
            step_id=first_step.id,
            requested_capability=(
                first_step.requested_capability or request.requested_capability
            ),
            status=ExecutionStatus.PENDING,
            input_document_id=initial_document_id,
        )
        saved = await self._execution_repository.save(execution)
        first_step.assign_execution(saved.id)
        await self._flow_step_repository.save(first_step)
        dispatched_initial_execution = None
        if self._dispatcher is not None:
            dispatched_initial_execution = await self._dispatcher.dispatch_if_bot_available(
                saved.id,
                preferred_bot_id=(
                    request.preferred_bot_id
                    if initial_step is SeoFlowStep.SEO_AUDIT
                    else None
                ),
            )

        return FlowSubmitResponse(
            flow=FlowResponse(**asdict(saved_flow)),
            steps=[FlowStepResponse(**asdict(step)) for step in saved_steps],
            initial_execution=ExecutionResponse.model_validate(saved),
            dispatched_initial_execution=dispatched_initial_execution,
        )


def _support_posts_mode(payload: dict[str, Any]) -> str:
    support_posts = payload.get("support_posts")
    if support_posts is None:
        return "auto"
    if not isinstance(support_posts, dict):
        raise ValueError("payload.support_posts must be an object")
    mode = support_posts.get("mode", "auto")
    if not isinstance(mode, str) or mode not in SUPPORT_POST_MODES:
        valid_modes = ", ".join(sorted(SUPPORT_POST_MODES))
        raise ValueError(f"payload.support_posts.mode must be one of: {valid_modes}")
    return mode


def _slug_from_page_url(page_url: str) -> str:
    path = page_url.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return path.rsplit("/", 1)[-1] or "home"
