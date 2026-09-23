from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from orchestrator.api.v1.auth import require_dashboard_operator
from orchestrator.api.v1.dependencies import (
    get_instagram_execution_result_use_case,
    list_instagram_executions_use_case,
)
from orchestrator.application.dtos import ExecutionListResponse, ExecutionSummaryResponse
from orchestrator.application.use_cases.instagram_executions import (
    GetInstagramExecutionResult,
    ListInstagramExecutions,
)
from orchestrator.core.config import get_settings
from orchestrator.domain.entities import ExecutionStatus

IN_FLIGHT_STATUSES = frozenset(
    {
        ExecutionStatus.PENDING,
        ExecutionStatus.QUEUED,
        ExecutionStatus.RUNNING,
        ExecutionStatus.CANCELLING,
    }
)

router = APIRouter(dependencies=[Depends(require_dashboard_operator)])


@router.get("/catalog")
async def instagram_catalog() -> dict[str, Any]:
    settings = get_settings()
    if not settings.instagram_backend_url or not settings.instagram_backend_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Instagram backend catalog is not configured",
        )
    url = settings.instagram_backend_url.rstrip("/") + "/api/orchestrator/instagram/catalog/"
    try:
        async with httpx.AsyncClient(timeout=settings.bot_request_timeout_seconds) as client:
            response = await client.get(
                url,
                headers={"X-Orchestrator-Token": settings.instagram_backend_token},
            )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Instagram backend catalog returned HTTP {exc.response.status_code}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Instagram backend catalog is unavailable",
        ) from exc
    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid Instagram catalog payload",
        )
    return payload


@router.get("/executions", response_model=ExecutionListResponse)
async def list_instagram_executions(
    capability: str | None = None,
    execution_status: str | None = Query(default=None, alias="status"),
    limit: int = 50,
    use_case: ListInstagramExecutions = Depends(list_instagram_executions_use_case),
) -> ExecutionListResponse:
    if not 1 <= limit <= 200:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="limit must be between 1 and 200",
        )
    parsed_status = None
    if execution_status:
        try:
            parsed_status = ExecutionStatus(execution_status)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid execution status",
            ) from exc
    try:
        executions, total = await use_case.execute(
            capability=capability,
            execution_status=parsed_status,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return ExecutionListResponse(
        items=[ExecutionSummaryResponse.model_validate(item) for item in executions],
        total=total,
    )


@router.get("/executions/{execution_id}/result")
async def get_instagram_execution_result(
    execution_id: UUID,
    use_case: GetInstagramExecutionResult = Depends(get_instagram_execution_result_use_case),
) -> dict[str, Any]:
    execution_status, payload = await use_case.execute(execution_id)
    if execution_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instagram execution not found",
        )
    if payload is None:
        if execution_status in IN_FLIGHT_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Execution result is not available yet",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution result not found",
        )
    return payload
