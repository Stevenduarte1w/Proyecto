from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.v1.dependencies import (
    db_session,
    page_execution_service,
    register_bot_use_case,
)
from orchestrator.application.dtos import (
    BotCatalogUpdatedMessage,
    BotCreateRequest,
    BotHeartbeatMessage,
    BotRegisterMessage,
    BotResponse,
    ExecutionProgressMessage,
    ExecutionResultRequest,
)
from orchestrator.application.use_cases.advance_workflow import AdvanceWorkflow
from orchestrator.application.use_cases.cancel_execution import CompleteExecutionCancellation
from orchestrator.application.use_cases.dispatch_execution import DispatchExecution
from orchestrator.application.use_cases.execution_checkpoint import (
    ExecutionEventError,
    ProcessExecutionCheckpoint,
    StartExecution,
)
from orchestrator.application.use_cases.execution_documents import SubmitExecutionResult
from orchestrator.application.use_cases.execution_progress import (
    ExecutionProgressError,
    RecordExecutionProgress,
)
from orchestrator.application.use_cases.reconcile_bot_connections import (
    TERMINAL_STATES,
    ReconcileBotConnections,
)
from orchestrator.application.use_cases.register_bot import RegisterBot
from orchestrator.application.use_cases.register_connected_bot import RegisterConnectedBot
from orchestrator.core.config import get_settings
from orchestrator.domain.backlinks import BACKLINKS_CAPABILITY
from orchestrator.infrastructure.bots.auth import (
    authenticated_bot_key,
    is_page_flow_bot,
    websocket_transport_is_secure,
)
from orchestrator.infrastructure.bots.ws_manager import bot_ws_manager
from orchestrator.infrastructure.mongo.repositories import MongoFlowDocumentRepository
from orchestrator.infrastructure.postgres.repositories import (
    SqlAlchemyBotRepository,
    SqlAlchemyExecutionCheckpointRepository,
    SqlAlchemyExecutionEventRepository,
    SqlAlchemyExecutionRepository,
    SqlAlchemyFlowRepository,
    SqlAlchemyFlowStepRepository,
)
from orchestrator.infrastructure.redis.locks import redis_lock
from orchestrator.infrastructure.redis.presence import RedisBotPresenceRepository
from orchestrator.infrastructure.seo_agent.management import (
    SqlAlchemySeoAgentManagementRepository,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.post("", response_model=BotResponse, status_code=status.HTTP_201_CREATED)
async def register_bot(
    payload: BotCreateRequest,
    use_case: Annotated[RegisterBot, Depends(register_bot_use_case)],
) -> BotResponse:
    return await use_case.execute(payload)


@router.websocket("/ws")
async def bot_websocket(
    websocket: WebSocket,
    session: Annotated[AsyncSession, Depends(db_session)],
) -> None:
    settings = get_settings()
    authenticated_bot_key_value = authenticated_bot_key(
        websocket.headers.get("authorization"),
        settings,
    )
    if not websocket_transport_is_secure(
        app_env=settings.app_env,
        websocket_scheme=websocket.url.scheme,
        forwarded_proto=websocket.headers.get("x-forwarded-proto"),
    ):
        await websocket.close(code=4403, reason="WSS is required in production")
        return
    await websocket.accept()
    presence = RedisBotPresenceRepository()
    bot_repository = SqlAlchemyBotRepository(session)
    execution_repository = SqlAlchemyExecutionRepository(session)
    checkpoint_repository = SqlAlchemyExecutionCheckpointRepository(session)
    event_repository = SqlAlchemyExecutionEventRepository(session)
    flow_repository = SqlAlchemyFlowRepository(session)
    flow_step_repository = SqlAlchemyFlowStepRepository(session)
    flow_document_repository = MongoFlowDocumentRepository()
    dispatcher = DispatchExecution(
        execution_repository=execution_repository,
        bot_repository=bot_repository,
        flow_step_repository=flow_step_repository,
        presence_repository=presence,
        command_gateway=bot_ws_manager,
        flow_document_repository=flow_document_repository,
    )
    workflow_engine = AdvanceWorkflow(
        flow_repository=flow_repository,
        flow_step_repository=flow_step_repository,
        execution_repository=execution_repository,
        flow_document_repository=flow_document_repository,
        dispatcher=dispatcher,
    )
    start_execution = StartExecution(
        execution_repository=execution_repository,
        flow_step_repository=flow_step_repository,
    )
    process_checkpoint = ProcessExecutionCheckpoint(
        execution_repository=execution_repository,
        checkpoint_repository=checkpoint_repository,
        flow_repository=flow_repository,
        flow_step_repository=flow_step_repository,
        flow_document_repository=flow_document_repository,
        workflow_engine=workflow_engine,
    )
    page_executions = page_execution_service()
    progress_recorder = RecordExecutionProgress(execution_repository, event_repository)
    cancellation_completer = CompleteExecutionCancellation(execution_repository, presence)
    reconciler = ReconcileBotConnections(execution_repository, presence)
    registered_bot_id = None
    registered_session_id = None

    try:
        raw_register_message = await websocket.receive_json()
        register_message = BotRegisterMessage.model_validate(raw_register_message)
        if register_message.type != "bot.register":
            await websocket.close(code=1008, reason="First message must be bot.register")
            return
        page_flow_bot = is_page_flow_bot(register_message.capabilities)
        if authenticated_bot_key_value is None and not page_flow_bot:
            await websocket.close(code=4401, reason="Invalid bot credentials")
            return
        if (
            authenticated_bot_key_value is not None
            and register_message.bot_key != authenticated_bot_key_value
        ):
            await websocket.close(code=4403, reason="Token is not valid for this bot_key")
            return
        if BACKLINKS_CAPABILITY in register_message.capabilities:
            try:
                catalog = BotCatalogUpdatedMessage.model_validate(
                    {
                        "type": "bot.catalog.updated",
                        "catalog_version": register_message.metadata.get("catalog_version"),
                        "companies": register_message.metadata.get("companies"),
                    }
                )
            except ValidationError as exc:
                await websocket.send_json(
                    {
                        "type": "error",
                        "code": "invalid_catalog",
                        "details": exc.errors(),
                    }
                )
                await websocket.close(code=1008, reason="Backlinks catalog is required")
                return
            register_message.metadata.update(
                catalog.model_dump(mode="json", exclude={"type"})
            )

        register_connected = RegisterConnectedBot(
            bot_repository=bot_repository,
            presence_repository=presence,
            presence_ttl_seconds=settings.bot_presence_ttl_seconds,
            heartbeat_deadline_seconds=settings.bot_heartbeat_grace_seconds,
        )
        existing_bot = await bot_repository.get_by_key(register_message.bot_key)
        if existing_bot is None:
            bot, session_id = await register_connected.execute(register_message)
            stale_executions = await reconciler.reconcile_registration(
                bot.id,
                register_message.active_executions,
            )
        else:
            async with redis_lock(f"lock:bot-session:{existing_bot.id}", 30) as acquired:
                if not acquired:
                    await websocket.close(code=1013, reason="Bot session is being reconciled")
                    return
                bot, session_id = await register_connected.execute(register_message)
                stale_executions = await reconciler.reconcile_registration(
                    bot.id,
                    register_message.active_executions,
                )
        registered_bot_id = bot.id
        registered_session_id = session_id
        await bot_ws_manager.connect(bot.id, session_id, websocket)
        await websocket.send_json(
            {
                "type": "bot.registered",
                "status": "ok",
                "session_id": session_id,
                "bot": bot.model_dump(mode="json"),
                "stale_executions": [str(item) for item in stale_executions],
            }
        )
        active_executions = await execution_repository.list_active_for_bot(bot.id)
        for active_execution in active_executions:
            if active_execution.status.value == "cancelling":
                await bot_ws_manager.send_cancel(bot.id, active_execution.id)
        redispatched = await dispatcher.dispatch_waiting_for_bot(
            bot,
            limit=register_message.available_slots,
            exclude_execution_ids=set(register_message.active_executions or []),
        )
        if redispatched:
            logger.info(
                "bot_waiting_executions_redispatched",
                bot_id=str(bot.id),
                count=len(redispatched),
            )

        while True:
            await session.rollback()
            message = await websocket.receive_json()
            message_type = message.get("type")

            if message_type == "bot.heartbeat":
                heartbeat = BotHeartbeatMessage.model_validate(message)
                heartbeat_recorded = await presence.heartbeat(
                    bot_id=bot.id,
                    available_slots=heartbeat.available_slots,
                    current_jobs=heartbeat.current_jobs,
                    ttl_seconds=settings.bot_presence_ttl_seconds,
                    session_id=session_id,
                    deadline_seconds=settings.bot_heartbeat_grace_seconds,
                )
                if not heartbeat_recorded:
                    await websocket.close(code=4409, reason="Bot session was superseded")
                    return
                if heartbeat.available_slots > 0:
                    redispatched = await dispatcher.dispatch_pending_for_bot(
                        bot,
                        limit=heartbeat.available_slots,
                    )
                    if redispatched:
                        logger.info(
                            "slot_controlled_waiting_executions_redispatched",
                            bot_id=str(bot.id),
                            count=len(redispatched),
                        )
                await websocket.send_json({"type": "bot.heartbeat.ack", "status": "ok"})
                continue

            if message_type == "bot.catalog.updated":
                try:
                    catalog = BotCatalogUpdatedMessage.model_validate(message)
                    if BACKLINKS_CAPABILITY not in bot.capabilities:
                        raise ValueError("Only a backlinks bot may publish this catalog")
                    stored_bot = await bot_repository.get(bot.id)
                    if stored_bot is None:
                        raise ValueError("Registered bot was not found")
                    stored_bot.metadata.update(
                        catalog.model_dump(mode="json", exclude={"type"})
                    )
                    await bot_repository.save(stored_bot)
                    bot.metadata = stored_bot.metadata
                    await websocket.send_json(
                        {
                            "type": "bot.catalog.ack",
                            "status": "ok",
                            "catalog_version": catalog.catalog_version,
                        }
                    )
                except (ValidationError, ValueError) as exc:
                    details = exc.errors() if isinstance(exc, ValidationError) else str(exc)
                    await websocket.send_json(
                        {
                            "type": "bot.catalog.ack",
                            "status": "error",
                            "details": details,
                        }
                    )
                continue

            if message_type == "execution.progress":
                try:
                    progress = ExecutionProgressMessage.model_validate(message)
                    receipt = await progress_recorder.execute(progress, bot.id)
                    await websocket.send_json(
                        {
                            "type": "execution.progress.ack",
                            "status": receipt.status,
                            "execution_id": str(progress.execution_id),
                            "event_id": str(progress.event_id),
                            "sequence": progress.sequence,
                            "expected_sequence": receipt.expected_sequence,
                        }
                    )
                except ValidationError as exc:
                    await websocket.send_json(
                        {
                            "type": "execution.progress.ack",
                            "status": "error",
                            "code": "invalid_message",
                            "details": exc.errors(),
                        }
                    )
                except ExecutionProgressError as exc:
                    await websocket.send_json(
                        {
                            "type": "execution.progress.ack",
                            "status": "error",
                            "code": exc.code,
                            "execution_id": message.get("execution_id"),
                            "event_id": message.get("event_id"),
                            "sequence": message.get("sequence"),
                            "message": str(exc),
                        }
                    )
                continue

            if message_type == "execution.cancelled":
                try:
                    execution_id = UUID(message["execution_id"])
                    cancelled = await cancellation_completer.execute(execution_id, bot.id)
                    await websocket.send_json(
                        {
                            "type": "execution.ack",
                            "status": "ok",
                            "execution_id": str(execution_id),
                            "execution_status": cancelled.status.value,
                        }
                    )
                except (KeyError, ValueError):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "invalid_message",
                            "message": "execution.cancelled requires a valid execution_id",
                        }
                    )
                except LookupError:
                    await websocket.send_json({"type": "execution.ack", "status": "not_found"})
                except PermissionError as exc:
                    await websocket.send_json(
                        {"type": "error", "code": "forbidden", "message": str(exc)}
                    )
                continue

            if message_type == "execution.started":
                try:
                    started_response = await start_execution.execute(
                        UUID(message["execution_id"]),
                        bot.id,
                    )
                    await websocket.send_json(
                        {
                            "type": "execution.ack",
                            "status": "ok",
                            "execution_status": started_response.status.value,
                            "internal_state": started_response.internal_state,
                        }
                    )
                except (KeyError, ValueError):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "invalid_message",
                            "message": "execution.started requires a valid execution_id",
                        }
                    )
                except ExecutionEventError as exc:
                    await websocket.send_json(
                        {"type": "error", "code": exc.code, "message": str(exc)}
                    )
                continue

            if message_type == "execution.checkpoint":
                try:
                    checkpoint_completion = await process_checkpoint.execute(
                        execution_id=UUID(message["execution_id"]),
                        actor_bot_id=bot.id,
                        checkpoint_name=message.get("checkpoint", ""),
                        payload=message.get("payload"),
                        reported_flow_id=message.get("flow_id"),
                        reported_capability=message.get("capability"),
                    )
                    await websocket.send_json(
                        {
                            "type": "execution.ack",
                            "status": "ok",
                            "execution_id": str(checkpoint_completion.execution.id),
                            "execution_status": checkpoint_completion.execution.status.value,
                            "internal_state": checkpoint_completion.execution.internal_state,
                            "checkpoint": checkpoint_completion.checkpoint,
                            "duplicate": checkpoint_completion.duplicate,
                            "created_executions": [
                                str(execution.id)
                                for execution in checkpoint_completion.created_executions
                            ],
                        }
                    )
                except (KeyError, ValueError):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "invalid_message",
                            "message": "execution.checkpoint requires a valid execution_id",
                        }
                    )
                except ExecutionEventError as exc:
                    await websocket.send_json(
                        {"type": "error", "code": exc.code, "message": str(exc)}
                    )
                except Exception as exc:
                    logger.exception(
                        "execution_checkpoint_processing_failed",
                        execution_id=message.get("execution_id"),
                        checkpoint=message.get("checkpoint"),
                        error=str(exc),
                    )
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "retryable_error",
                            "message": "Checkpoint could not be processed; retry the same message",
                        }
                    )
                continue

            if message_type in {
                "execution.succeeded",
                "execution.failed",
                "execution.result",
            }:
                try:
                    execution_id = UUID(message["execution_id"])
                except (KeyError, ValueError):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "invalid_message",
                            "message": "Terminal event requires a valid execution_id",
                        }
                    )
                    continue
                async with redis_lock(f"lock:terminal:{execution_id}", 30) as acquired:
                    if not acquired:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "retryable_error",
                                "message": "Execution result is being processed; retry",
                            }
                        )
                        continue
                    raw_execution = await execution_repository.get(execution_id)
                    if raw_execution is None:
                        await websocket.send_json(
                            {"type": "execution.ack", "status": "not_found"}
                        )
                        continue
                    if raw_execution.bot_id != bot.id:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "forbidden",
                                "message": "Execution is assigned to a different bot",
                            }
                        )
                        continue
                    if raw_execution.status in TERMINAL_STATES:
                        await presence.release_slot(bot.id, execution_id)
                        await websocket.send_json(
                            {
                                "type": "execution.ack",
                                "status": "ok",
                                "execution_status": raw_execution.status.value,
                                "error": raw_execution.error_message,
                            }
                        )
                        continue
                    if raw_execution.status.value == "cancelling":
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "invalid_state",
                                "message": (
                                    "Execution is cancelling; finish the current site and send "
                                    "execution.cancelled"
                                ),
                            }
                        )
                        continue

                    result = _execution_result_request(message_type, message)
                    result_completion = await SubmitExecutionResult(
                        execution_repository=execution_repository,
                        flow_step_repository=flow_step_repository,
                        flow_document_repository=flow_document_repository,
                        workflow_engine=workflow_engine,
                        seo_management_repository=SqlAlchemySeoAgentManagementRepository(),
                        page_execution_service=page_executions,
                    ).execute(execution_id, result)
                    if result_completion is None:
                        await websocket.send_json(
                            {"type": "execution.ack", "status": "not_found"}
                        )
                        continue
                    await presence.release_slot(bot.id, execution_id)
                    await websocket.send_json(
                        {
                            "type": "execution.ack",
                            "status": "ok",
                            "execution_status": result_completion.execution.status.value,
                            "error": result_completion.execution.error_message,
                        }
                    )
                continue

            await websocket.send_json(
                {
                    "type": "error",
                    "code": "unsupported_message_type",
                    "message": f"Unsupported message type: {message_type}",
                }
            )

    except ValidationError as exc:
        await websocket.send_json(
            {"type": "error", "code": "invalid_message", "details": exc.errors()}
        )
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        pass
    finally:
        if registered_bot_id is not None:
            await presence.mark_offline(registered_bot_id, registered_session_id)
            await bot_ws_manager.disconnect(registered_bot_id, registered_session_id)


def _execution_result_request(
    message_type: str,
    message: dict[str, Any],
) -> ExecutionResultRequest:
    if message_type == "execution.result":
        succeeded = message.get("ok") is True
    else:
        succeeded = message_type == "execution.succeeded"
    return ExecutionResultRequest(
        status="succeeded" if succeeded else "failed",
        payload=message.get("payload", {}),
        error=message.get("error") or (None if succeeded else f"{message_type} reported failure"),
    )
