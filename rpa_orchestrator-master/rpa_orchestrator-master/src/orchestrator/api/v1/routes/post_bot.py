"""Canal WebSocket aislado del bot de posts.

A diferencia de `/api/v1/bots/ws`, este endpoint **sí despacha trabajo** pero no
participa del motor de workflows SEO: no avanza etapas ni escribe en `flows`,
`flow_steps`, `executions` o `execution_checkpoints`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

import structlog
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from orchestrator.api.v1.auth import require_dashboard_operator
from orchestrator.api.v1.dependencies import post_bot_service
from orchestrator.application.post_bot import (
    PostBotHeartbeatMessage,
    PostBotJobConflictError,
    PostBotJobCreateRequest,
    PostBotJobOwnershipError,
    PostBotJobResultMessage,
    PostBotJobStartedMessage,
    PostBotJobStateError,
    PostBotRegisterMessage,
    PostBotService,
    job_input_document,
)
from orchestrator.core.config import get_settings
from orchestrator.domain.post_bot import POST_BOT_CAPABILITIES
from orchestrator.infrastructure.bots.auth import (
    authenticated_bot_key,
    websocket_transport_is_secure,
)
from orchestrator.infrastructure.bots.post_bot_ws_manager import post_bot_ws_manager

router = APIRouter()
logger = structlog.get_logger(__name__)

JobState = Literal["queued", "dispatched", "running", "succeeded", "failed", "cancelled"]


@router.websocket("/ws")
async def post_bot_websocket(
    websocket: WebSocket,
    service: Annotated[PostBotService, Depends(post_bot_service)],
) -> None:
    settings = get_settings()
    authenticated_key = authenticated_bot_key(
        websocket.headers.get("authorization"),
        settings,
    )
    if authenticated_key is None:
        await websocket.close(code=4401, reason="Invalid bot credentials")
        return
    if not websocket_transport_is_secure(
        app_env=settings.app_env,
        websocket_scheme=websocket.url.scheme,
        forwarded_proto=websocket.headers.get("x-forwarded-proto"),
    ):
        await websocket.close(code=4403, reason="WSS is required in production")
        return

    await websocket.accept()
    worker_id: UUID | None = None
    session_id = uuid4()

    try:
        try:
            registration = PostBotRegisterMessage.model_validate(await websocket.receive_json())
        except ValidationError as exc:
            await _send_error(
                websocket,
                code="invalid_first_message",
                message=str(exc),
                retryable=False,
            )
            await websocket.close(code=4400, reason="First message must be bot.register")
            return

        if registration.bot_key != authenticated_key:
            await _send_error(
                websocket,
                code="forbidden",
                message="Token is not valid for this bot_key",
                retryable=False,
            )
            await websocket.close(code=4403, reason="Token is not valid for this bot_key")
            return

        try:
            worker, requeued = await service.register(registration, session_id)
        except PermissionError as exc:
            await _send_error(websocket, code="worker_disabled", message=str(exc), retryable=False)
            await websocket.close(code=4403, reason="Post bot worker disabled")
            return

        worker_id = UUID(str(worker["id"]))
        await post_bot_ws_manager.connect(
            worker_id,
            session_id,
            websocket,
            registration.capabilities,
        )
        await websocket.send_json(
            jsonable_encoder(
                {
                    "type": "bot.registered",
                    "status": "ok",
                    "session_id": str(session_id),
                    "server_time": datetime.now(UTC),
                    "heartbeat_interval_seconds": max(
                        5,
                        settings.post_bot_presence_ttl_seconds // 2,
                    ),
                    "bot": worker,
                    "requeued_jobs": [str(job_id) for job_id in requeued],
                }
            )
        )
        dispatched = await service.dispatch_pending(
            worker_id=worker_id,
            limit=registration.available_slots,
        )
        if dispatched:
            logger.info(
                "post_bot_jobs_dispatched_on_register",
                worker_id=str(worker_id),
                count=len(dispatched),
            )

        while True:
            message = await websocket.receive_json()
            message_type = message.get("type") if isinstance(message, dict) else None

            if message_type == "bot.heartbeat":
                try:
                    heartbeat = PostBotHeartbeatMessage.model_validate(message)
                except ValidationError as exc:
                    await _send_validation_error(websocket, exc)
                    continue
                await service.heartbeat(worker_id, heartbeat)
                await websocket.send_json({"type": "bot.heartbeat.ack", "status": "ok"})
                if heartbeat.available_slots > 0:
                    await service.dispatch_pending(
                        worker_id=worker_id,
                        limit=heartbeat.available_slots,
                    )
                continue

            if message_type == "execution.started":
                try:
                    started = PostBotJobStartedMessage.model_validate(message)
                    job = await service.mark_running(started.execution_id, worker_id)
                except ValidationError as exc:
                    await _send_validation_error(websocket, exc)
                    continue
                except LookupError:
                    await websocket.send_json(
                        {"type": "execution.ack", "status": "not_found"}
                    )
                    continue
                except PostBotJobOwnershipError as exc:
                    await _send_error(
                        websocket, code="forbidden", message=str(exc), retryable=False
                    )
                    continue
                except PostBotJobStateError as exc:
                    await _send_error(
                        websocket, code="invalid_state", message=str(exc), retryable=False
                    )
                    continue
                await websocket.send_json(
                    {
                        "type": "execution.ack",
                        "status": "ok",
                        "execution_id": str(started.execution_id),
                        "job_status": job["status"],
                    }
                )
                continue

            if message_type in {"execution.succeeded", "execution.failed"}:
                try:
                    result_message = PostBotJobResultMessage.model_validate(message)
                    job, duplicate = await service.complete(worker_id, result_message)
                except ValidationError as exc:
                    await _send_validation_error(websocket, exc)
                    continue
                except LookupError:
                    await websocket.send_json(
                        {"type": "execution.ack", "status": "not_found"}
                    )
                    continue
                except PostBotJobOwnershipError as exc:
                    await _send_error(
                        websocket, code="forbidden", message=str(exc), retryable=False
                    )
                    continue
                await websocket.send_json(
                    {
                        "type": "execution.ack",
                        "status": "ok",
                        "execution_id": str(result_message.execution_id),
                        "job_status": job["status"],
                        "duplicate": duplicate,
                    }
                )
                continue

            await _send_error(
                websocket,
                code="unsupported_message_type",
                message=f"Unsupported message type: {message_type}",
                retryable=False,
            )

    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - se informa y se cierra la sesión
        logger.exception(
            "post_bot_websocket_failed",
            worker_id=str(worker_id) if worker_id else None,
            error=str(exc),
        )
        try:
            await _send_error(
                websocket,
                code="temporary_error",
                message="The message could not be processed; reconnect and retry",
                retryable=True,
            )
            await websocket.close(code=1011, reason="Post bot processing failed")
        except RuntimeError:
            pass
    finally:
        if worker_id is not None:
            await post_bot_ws_manager.disconnect(worker_id, session_id)
            await service.disconnect(worker_id, session_id)


@router.post(
    "/jobs",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_dashboard_operator)],
)
async def enqueue_post_bot_job(
    payload: PostBotJobCreateRequest,
    service: Annotated[PostBotService, Depends(post_bot_service)],
    response: Response,
) -> dict[str, Any]:
    try:
        job, duplicate = await service.enqueue(payload)
    except PostBotJobConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if duplicate:
        response.status_code = status.HTTP_200_OK
    return {**job, "duplicate": duplicate}


@router.get("/jobs", dependencies=[Depends(require_dashboard_operator)])
async def list_post_bot_jobs(
    service: Annotated[PostBotService, Depends(post_bot_service)],
    job_status: Annotated[JobState | None, Query(alias="status")] = None,
    capability: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    if capability is not None and capability not in POST_BOT_CAPABILITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported capability: {capability}",
        )
    return await service.list_jobs(job_status, capability, limit)


@router.get("/jobs/{job_id}", dependencies=[Depends(require_dashboard_operator)])
async def get_post_bot_job(
    job_id: UUID,
    service: Annotated[PostBotService, Depends(post_bot_service)],
) -> dict[str, Any]:
    job = await service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post bot job not found")
    return job


@router.get("/jobs/{job_id}/input")
async def get_post_bot_job_input(
    job_id: UUID,
    request: Request,
    service: Annotated[PostBotService, Depends(post_bot_service)],
) -> dict[str, Any]:
    """Documento que el bot descarga desde `input_url`.

    Se autentica con el mismo Bearer de `BOT_TOKENS` que usa el WebSocket, no con
    el usuario del dashboard, porque quien lo consume es el bot. Además solo
    entrega trabajos asignados al worker de ese `bot_key`.
    """
    authenticated_key = authenticated_bot_key(
        request.headers.get("Authorization"),
        get_settings(),
    )
    if authenticated_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": 'Bearer realm="RPA Bots"'},
        )
    job = await service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post bot job not found")
    worker = await service.get_worker_by_key(authenticated_key)
    if worker is None or job["worker_id"] != worker["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Job is assigned to a different worker",
        )
    return job_input_document(job)


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(require_dashboard_operator)])
async def cancel_post_bot_job(
    job_id: UUID,
    service: Annotated[PostBotService, Depends(post_bot_service)],
) -> dict[str, Any]:
    try:
        return await service.cancel(job_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post bot job not found",
        ) from exc
    except PostBotJobStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/workers", dependencies=[Depends(require_dashboard_operator)])
async def list_post_bot_workers(
    service: Annotated[PostBotService, Depends(post_bot_service)],
) -> list[dict[str, Any]]:
    return await service.list_workers()


@router.get("/overview", dependencies=[Depends(require_dashboard_operator)])
async def post_bot_overview(
    service: Annotated[PostBotService, Depends(post_bot_service)],
) -> dict[str, Any]:
    return await service.overview()


async def _send_validation_error(websocket: WebSocket, exc: ValidationError) -> None:
    await _send_error(websocket, code="invalid_message", message=str(exc), retryable=False)


async def _send_error(
    websocket: WebSocket,
    *,
    code: str,
    message: str,
    retryable: bool,
) -> None:
    await websocket.send_json(
        {
            "type": "error",
            "code": code,
            "message": message,
            "retryable": retryable,
        }
    )
