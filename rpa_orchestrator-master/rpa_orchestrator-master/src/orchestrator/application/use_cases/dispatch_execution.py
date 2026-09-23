from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from orchestrator.application.dtos import BotResponse, DispatchExecutionRequest, ExecutionResponse
from orchestrator.domain.backlinks import BACKLINKS_CAPABILITY, BACKLINKS_STAGE
from orchestrator.domain.entities import Bot, SeoFlowStep
from orchestrator.domain.indexing import INDEXING_CAPABILITY, INDEXING_STAGE
from orchestrator.domain.pagespeed import PAGESPEED_CAPABILITY
from orchestrator.domain.ports import (
    BotCommandGateway,
    BotPresenceRepository,
    BotRepository,
    ExecutionRepository,
    FlowDocumentRepository,
    FlowStepRepository,
)
from orchestrator.domain.workflow import SEO_MAIN_SUPPORTED_STAGES

logger = structlog.get_logger(__name__)


class DispatchExecution:
    def __init__(
        self,
        execution_repository: ExecutionRepository,
        bot_repository: BotRepository,
        flow_step_repository: FlowStepRepository,
        presence_repository: BotPresenceRepository,
        command_gateway: BotCommandGateway,
        flow_document_repository: FlowDocumentRepository | None = None,
    ) -> None:
        self._execution_repository = execution_repository
        self._bot_repository = bot_repository
        self._flow_step_repository = flow_step_repository
        self._presence_repository = presence_repository
        self._command_gateway = command_gateway
        self._flow_document_repository = flow_document_repository

    async def execute(self, request: DispatchExecutionRequest) -> ExecutionResponse:
        return await self.dispatch(
            request.execution_id,
            fail_when_no_bot=True,
            preferred_bot_id=request.preferred_bot_id,
        )

    async def dispatch(
        self,
        execution_id: UUID,
        *,
        fail_when_no_bot: bool,
        preferred_bot_id: UUID | None = None,
    ) -> ExecutionResponse:
        execution = await self._execution_repository.get(execution_id)
        if execution is None:
            raise ValueError("Execution not found")

        step = None
        stage = None
        if execution.step_id is not None:
            step = await self._flow_step_repository.get(execution.step_id)
            if step is not None:
                stage = step.step_name.value
                if execution.requested_capability == INDEXING_CAPABILITY:
                    stage = INDEXING_STAGE
        elif execution.requested_capability == INDEXING_CAPABILITY:
            stage = INDEXING_STAGE
        elif execution.requested_capability == PAGESPEED_CAPABILITY:
            stage = "pagespeed"
        elif execution.requested_capability == BACKLINKS_CAPABILITY:
            stage = BACKLINKS_STAGE

        if (
            execution.requested_capability == BACKLINKS_CAPABILITY
            and execution.input_document_id is None
        ):
            execution.mark_failed("Backlinks input document is not available")
            saved = await self._execution_repository.save(execution)
            return ExecutionResponse.model_validate(saved)

        if (
            execution.requested_capability == "seo.main"
            and (step is None or step.step_name not in SEO_MAIN_SUPPORTED_STAGES)
        ):
            error = f"Unsupported stage for seo.main: {stage or 'missing'}"
            execution.mark_failed(error)
            saved = await self._execution_repository.save(execution)
            if step is not None:
                step.mark_failed(error)
                await self._flow_step_repository.save(step)
            return ExecutionResponse.model_validate(saved)

        command_payload = None
        if (
            execution.requested_capability == "seo.main"
            and step is not None
            and step.step_name is SeoFlowStep.SEO_AUDIT
        ):
            command_payload = await self._load_command_payload(execution, step)
            if command_payload is None:
                error = "SEO audit input document is not available"
                execution.mark_failed(error)
                saved = await self._execution_repository.save(execution)
                step.mark_failed(error)
                await self._flow_step_repository.save(step)
                return ExecutionResponse.model_validate(saved)
        elif execution.requested_capability == INDEXING_CAPABILITY:
            if (
                self._flow_document_repository is None
                or execution.input_document_id is None
            ):
                error = "Indexing input document is not available"
                execution.mark_failed(error)
                saved = await self._execution_repository.save(execution)
                if step is not None:
                    step.mark_failed(error)
                    await self._flow_step_repository.save(step)
                return ExecutionResponse.model_validate(saved)
            command_payload = await self._load_command_payload(execution, step)
            if command_payload is None:
                error = "Indexing input document is invalid"
                execution.mark_failed(error)
                saved = await self._execution_repository.save(execution)
                if step is not None:
                    step.mark_failed(error)
                    await self._flow_step_repository.save(step)
                return ExecutionResponse.model_validate(saved)

        bot = None
        slot_reserved = False
        target_bot_id = preferred_bot_id or execution.bot_id
        candidates = await self._bot_repository.list_enabled_by_capability(
            execution.requested_capability
        )
        for candidate in candidates:
            if target_bot_id is not None and candidate.id != target_bot_id:
                continue
            if not await self._presence_repository.is_online(candidate.id):
                continue
            if not await self._presence_repository.reserve_slot(
                candidate.id,
                execution.id,
                candidate.max_concurrency,
            ):
                continue
            slot_reserved = True
            bot = candidate
            break

        if bot is None:
            if fail_when_no_bot:
                execution.mark_failed("No online bot supports the requested capability")
                saved = await self._execution_repository.save(execution)
                return ExecutionResponse.model_validate(saved)
            return ExecutionResponse.model_validate(execution)

        execution.assign_bot(bot.id)
        execution.mark_queued()
        try:
            saved = await self._execution_repository.save(execution)
        except Exception:
            if slot_reserved:
                await self._presence_repository.release_slot(bot.id, execution.id)
            raise

        try:
            await self._command_gateway.send_execution(
                bot_id=bot.id,
                flow_id=saved.flow_id,
                execution_id=saved.id,
                capability=saved.requested_capability,
                stage=stage,
                input_document_id=saved.input_document_id,
                command_payload=command_payload,
            )
        except Exception as exc:
            if slot_reserved:
                await self._presence_repository.release_slot(bot.id, execution.id)
            execution.return_to_pending()
            saved = await self._execution_repository.save(execution)
            logger.warning(
                "execution_dispatch_send_failed",
                execution_id=str(execution.id),
                bot_id=str(bot.id),
                error=str(exc),
            )
        return ExecutionResponse.model_validate(saved)

    async def _load_command_payload(
        self,
        execution: Any,
        step: Any,
    ) -> dict[str, Any] | None:
        if self._flow_document_repository is None or execution.input_document_id is None:
            return None
        input_document = await self._flow_document_repository.get_document(
            execution.input_document_id
        )
        if input_document is None:
            return None
        payload = input_document.get("payload")
        if not isinstance(payload, dict):
            return None
        return dict(payload)

    async def dispatch_if_bot_available(
        self,
        execution_id: UUID,
        *,
        preferred_bot_id: UUID | None = None,
    ) -> ExecutionResponse:
        return await self.dispatch(
            execution_id,
            fail_when_no_bot=False,
            preferred_bot_id=preferred_bot_id,
        )

    async def list_online_bots_by_capability(self, capability: str) -> list[Bot]:
        candidates = await self._bot_repository.list_enabled_by_capability(capability)
        online: list[Bot] = []
        for candidate in candidates:
            if await self._presence_repository.is_online(candidate.id):
                online.append(candidate)
        return online

    async def dispatch_waiting_for_bot(
        self,
        bot: BotResponse,
        *,
        limit: int | None = None,
        exclude_execution_ids: set[UUID] | None = None,
    ) -> list[ExecutionResponse]:
        dispatch_limit = bot.max_concurrency if limit is None else min(limit, bot.max_concurrency)
        if dispatch_limit <= 0:
            return []
        excluded = exclude_execution_ids or set()
        executions = await self._execution_repository.list_dispatchable_for_bot(
            bot.id,
            bot.capabilities,
            dispatch_limit + len(excluded),
        )
        responses: list[ExecutionResponse] = []
        for execution in executions:
            if execution.id in excluded:
                continue
            responses.append(
                await self.dispatch_if_bot_available(
                    execution.id,
                    preferred_bot_id=bot.id,
                )
            )
            if len(responses) >= dispatch_limit:
                break
        return responses

    async def dispatch_pending_for_bot(
        self,
        bot: BotResponse,
        *,
        limit: int,
    ) -> list[ExecutionResponse]:
        dispatch_limit = min(limit, bot.max_concurrency)
        if dispatch_limit <= 0:
            return []
        executions = await self._execution_repository.list_pending_for_bot(
            bot.id,
            bot.capabilities,
            dispatch_limit,
        )
        responses: list[ExecutionResponse] = []
        for execution in executions:
            responses.append(
                await self.dispatch_if_bot_available(
                    execution.id,
                    preferred_bot_id=bot.id,
                )
            )
        return responses

    async def get_execution(self, execution_id: UUID) -> ExecutionResponse | None:
        execution = await self._execution_repository.get(execution_id)
        if execution is None:
            return None
        return ExecutionResponse.model_validate(execution)
