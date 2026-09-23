from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from orchestrator.api.v1.dependencies import post_monitor_service
from orchestrator.application.post_monitor import (
    PostMonitorAlertUpdateRequest,
    PostMonitorEventConflictError,
    PostMonitorEventReceipt,
    PostMonitorHeartbeatMessage,
    PostMonitorProjectionConflictError,
    PostMonitorRegisterMessage,
    PostMonitorRunResultMessage,
    PostMonitorService,
    PostMonitorThresholdAlertMessage,
)
from orchestrator.core.config import get_settings

router = APIRouter()
logger = structlog.get_logger(__name__)

RunStatus = Literal["succeeded", "failed", "partial", "cancelled"]
AlertStatus = Literal["open", "acknowledged", "resolved", "dismissed"]
AlertSeverity = Literal["info", "warning", "critical"]


@router.websocket("/ws")
async def post_monitor_websocket(
    websocket: WebSocket,
    service: Annotated[PostMonitorService, Depends(post_monitor_service)],
) -> None:
    settings = get_settings()
    await websocket.accept()
    if not _valid_post_monitor_token(
        websocket.headers.get("Authorization", ""),
        settings.post_monitor_ws_token,
    ):
        await websocket.close(code=4401, reason="Invalid post monitor token")
        return

    registered_bot_id: UUID | None = None
    registered_bot_key: str | None = None
    try:
        raw_registration = await websocket.receive_json()
        try:
            registration = PostMonitorRegisterMessage.model_validate(raw_registration)
        except ValidationError as exc:
            await _send_error(
                websocket,
                code="invalid_first_message",
                message=str(exc),
                retryable=False,
            )
            await websocket.close(code=4400, reason="Invalid registration")
            return

        try:
            bot = await service.register(registration)
        except PermissionError as exc:
            await _send_error(
                websocket,
                code="bot_disabled",
                message=str(exc),
                retryable=False,
            )
            await websocket.close(code=4403, reason="Post monitor bot disabled")
            return

        registered_bot_id = UUID(str(bot["id"]))
        registered_bot_key = registration.bot_key
        session_id = uuid4()
        await websocket.send_json(
            jsonable_encoder(
                {
                    "type": "post_monitor.registered",
                    "schema_version": "post-monitor.registered.v1",
                    "status": "ok",
                    "session_id": session_id,
                    "server_time": datetime.now(UTC),
                    "heartbeat_interval_seconds": min(
                        25,
                        max(5, settings.post_monitor_presence_ttl_seconds // 2),
                    ),
                    "max_message_bytes": settings.post_monitor_max_message_bytes,
                    "bot": bot,
                }
            )
        )

        while True:
            message = await websocket.receive_json()
            message_type = message.get("type") if isinstance(message, dict) else None

            if message_type == "post_monitor.heartbeat":
                try:
                    heartbeat = PostMonitorHeartbeatMessage.model_validate(message)
                    await service.heartbeat(registered_bot_id, heartbeat)
                    await websocket.send_json(
                        {
                            "type": "post_monitor.heartbeat.ack",
                            "status": "ok",
                            "server_time": datetime.now(UTC).isoformat(),
                        }
                    )
                except ValidationError as exc:
                    await _send_validation_error(websocket, exc)
                continue

            if message_type == "post_monitor.run.result":
                try:
                    result_message = PostMonitorRunResultMessage.model_validate(message)
                    receipt = await service.ingest_result(
                        registered_bot_id,
                        registered_bot_key,
                        result_message,
                    )
                    await _send_receipt(websocket, receipt)
                except ValidationError as exc:
                    await _send_validation_error(websocket, exc, message.get("event_id"))
                except PermissionError as exc:
                    await _send_error(
                        websocket,
                        code="forbidden",
                        message=str(exc),
                        event_id=message.get("event_id"),
                        retryable=False,
                    )
                except (PostMonitorEventConflictError, PostMonitorProjectionConflictError) as exc:
                    await _send_error(
                        websocket,
                        code="event_id_conflict",
                        message=str(exc),
                        event_id=message.get("event_id"),
                        retryable=False,
                    )
                continue

            if message_type == "post_monitor.threshold.alert":
                try:
                    alert_message = PostMonitorThresholdAlertMessage.model_validate(message)
                    receipt = await service.ingest_alert(
                        registered_bot_id,
                        registered_bot_key,
                        alert_message,
                    )
                    await _send_receipt(websocket, receipt)
                except ValidationError as exc:
                    await _send_validation_error(websocket, exc, message.get("event_id"))
                except PermissionError as exc:
                    await _send_error(
                        websocket,
                        code="forbidden",
                        message=str(exc),
                        event_id=message.get("event_id"),
                        retryable=False,
                    )
                except (PostMonitorEventConflictError, PostMonitorProjectionConflictError) as exc:
                    await _send_error(
                        websocket,
                        code="event_id_conflict",
                        message=str(exc),
                        event_id=message.get("event_id"),
                        retryable=False,
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
    except Exception as exc:
        logger.exception(
            "post_monitor_websocket_failed",
            bot_id=str(registered_bot_id) if registered_bot_id else None,
            error=str(exc),
        )
        try:
            await _send_error(
                websocket,
                code="temporary_storage_error",
                message=(
                    "The event could not be processed; reconnect and retry "
                    "unacknowledged events"
                ),
                retryable=True,
            )
            await websocket.close(code=1011, reason="Post monitor processing failed")
        except RuntimeError:
            pass


@router.get("/overview")
async def post_monitor_overview(
    service: Annotated[PostMonitorService, Depends(post_monitor_service)],
) -> dict[str, object]:
    return await service.overview()


@router.get("/runs")
async def list_post_monitor_runs(
    service: Annotated[PostMonitorService, Depends(post_monitor_service)],
    status: Annotated[RunStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    return await service.list_runs(status, limit)


@router.get("/alerts")
async def list_post_monitor_alerts(
    service: Annotated[PostMonitorService, Depends(post_monitor_service)],
    status: Annotated[AlertStatus | None, Query()] = None,
    severity: Annotated[AlertSeverity | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    return await service.list_alerts(status, severity, limit)


@router.patch("/alerts/{alert_id}")
async def update_post_monitor_alert(
    alert_id: UUID,
    payload: PostMonitorAlertUpdateRequest,
    service: Annotated[PostMonitorService, Depends(post_monitor_service)],
) -> dict[str, object]:
    alert = await service.update_alert(alert_id, payload.status)
    if alert is None:
        raise HTTPException(status_code=404, detail="Post monitor alert not found")
    return alert


def _valid_post_monitor_token(header: str, expected_token: str) -> bool:
    if not expected_token:
        return True
    if not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[7:], expected_token)


async def _send_receipt(
    websocket: WebSocket,
    receipt: PostMonitorEventReceipt,
) -> None:
    await websocket.send_json(
        jsonable_encoder(
            {
                "type": "post_monitor.event.ack",
                "status": "accepted",
                **receipt.model_dump(),
            }
        )
    )


async def _send_validation_error(
    websocket: WebSocket,
    exc: ValidationError,
    event_id: object | None = None,
) -> None:
    await _send_error(
        websocket,
        code="invalid_message",
        message=str(exc),
        event_id=event_id,
        retryable=False,
    )


async def _send_error(
    websocket: WebSocket,
    *,
    code: str,
    message: str,
    retryable: bool,
    event_id: object | None = None,
) -> None:
    payload = {
        "type": "post_monitor.error",
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if event_id is not None:
        payload["event_id"] = str(event_id)
    await websocket.send_json(payload)
