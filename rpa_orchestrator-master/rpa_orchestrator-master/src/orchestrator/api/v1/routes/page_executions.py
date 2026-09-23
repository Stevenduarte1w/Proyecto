from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status

from orchestrator.api.v1.dependencies import page_execution_service
from orchestrator.application.use_cases.page_executions import PageExecutionService

router = APIRouter()
PageExecutionServiceDependency = Annotated[
    PageExecutionService,
    Depends(page_execution_service),
]
JsonBody = Annotated[Any, Body()]


@router.get("/campaigns")
async def list_campaigns(
    service: PageExecutionServiceDependency,
) -> list[dict[str, Any]]:
    return await service.list_campaigns()


@router.get("/campaigns/{campaign_id}/pages")
async def list_campaign_pages(
    campaign_id: int,
    service: PageExecutionServiceDependency,
) -> list[dict[str, Any]]:
    return await service.list_pages(campaign_id)


@router.get("/pages/{campaign_page_id}/executions")
async def list_page_executions(
    campaign_page_id: int,
    service: PageExecutionServiceDependency,
) -> list[dict[str, Any]]:
    return await service.list_page_executions(campaign_page_id)


@router.post("/{queue_execution_id}/sync")
async def sync_page_execution(
    queue_execution_id: int,
    service: PageExecutionServiceDependency,
) -> dict[str, Any]:
    try:
        return await service.sync_execution(queue_execution_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.put("/{queue_execution_id}/artifacts/{filename}")
async def upsert_page_execution_artifact(
    queue_execution_id: int,
    filename: str,
    payload: JsonBody,
    service: PageExecutionServiceDependency,
) -> dict[str, Any]:
    try:
        return await service.store_artifact(queue_execution_id, filename, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.put("/{queue_execution_id}/artifacts")
async def upsert_page_execution_artifacts(
    queue_execution_id: int,
    payload: Annotated[dict[str, Any], Body()],
    service: PageExecutionServiceDependency,
) -> dict[str, Any]:
    try:
        return await service.store_artifacts(queue_execution_id, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.put("/{queue_execution_id}/log")
async def upsert_page_execution_log(
    queue_execution_id: int,
    payload: JsonBody,
    service: PageExecutionServiceDependency,
) -> dict[str, Any]:
    try:
        return await service.store_log(queue_execution_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get("/{queue_execution_id}/artifacts")
async def list_page_execution_artifacts(
    queue_execution_id: int,
    service: PageExecutionServiceDependency,
) -> dict[str, Any]:
    try:
        execution = await service.get_execution(queue_execution_id)
        if execution is None:
            raise LookupError(
                f"Page execution {queue_execution_id} has not been synchronized"
            )
        artifacts = await service.list_artifacts(queue_execution_id)
        return {
            "queue_execution_id": queue_execution_id,
            "campaign_id": execution["campaign_id"],
            "campaign_name": execution["campaign_name"],
            "campaign_page_id": execution["campaign_page_id"],
            "page_slug": execution["page_slug"],
            "summary": execution.get("artifacts", {}),
            "items": artifacts,
        }
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{queue_execution_id}/artifacts/{filename}")
async def get_page_execution_artifact(
    queue_execution_id: int,
    filename: str,
    service: PageExecutionServiceDependency,
) -> dict[str, Any]:
    try:
        artifact = await service.get_artifact(queue_execution_id, filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return artifact


@router.get("/{queue_execution_id}/log")
async def get_page_execution_log(
    queue_execution_id: int,
    service: PageExecutionServiceDependency,
) -> dict[str, Any]:
    try:
        document = await service.get_log(queue_execution_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Live execution log is not available",
        )
    return document


@router.get("/{queue_execution_id}")
async def get_page_execution(
    queue_execution_id: int,
    service: PageExecutionServiceDependency,
) -> dict[str, Any]:
    execution = await service.get_execution(queue_execution_id)
    if execution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Page execution has not been synchronized",
        )
    return execution
