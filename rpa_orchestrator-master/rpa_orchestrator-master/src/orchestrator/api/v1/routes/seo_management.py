from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder

from orchestrator.api.v1.dependencies import seo_management_service
from orchestrator.application.import_template import (
    IMPORT_TEMPLATE_FILENAME,
    build_import_template,
)
from orchestrator.application.seo_management import (
    AdminResource,
    CampaignPageCreateRequest,
    CampaignPageUpdateRequest,
    ImportPagesRequest,
    PostGroupCreateRequest,
    PostGroupUpdateRequest,
    RetryQueueRequest,
    RunDailyRequest,
    RunNowRequest,
    SchedulePagesRequest,
    SeoManagementService,
)

XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

router = APIRouter()
SeoManagementDependency = Annotated[
    SeoManagementService,
    Depends(seo_management_service),
]


@router.get("/campaigns")
async def list_campaigns(
    service: SeoManagementDependency,
) -> list[dict[str, Any]]:
    return await _execute(service.list_campaigns())


@router.get("/admin/{resource}")
async def list_admin_records(
    resource: AdminResource,
    service: SeoManagementDependency,
) -> list[dict[str, Any]]:
    return await _execute(service.list_admin_records(resource))


@router.post("/admin/{resource}", status_code=status.HTTP_201_CREATED)
async def create_admin_record(
    resource: AdminResource,
    payload: dict[str, Any],
    service: SeoManagementDependency,
) -> dict[str, Any]:
    return await _execute(service.create_admin_record(resource, payload))


@router.put("/admin/{resource}/{record_id}")
async def update_admin_record(
    resource: AdminResource,
    record_id: int,
    payload: dict[str, Any],
    service: SeoManagementDependency,
) -> dict[str, Any]:
    return await _execute(service.update_admin_record(resource, record_id, payload))


@router.delete("/admin/{resource}/{record_id}")
async def delete_admin_record(
    resource: AdminResource,
    record_id: int,
    service: SeoManagementDependency,
) -> dict[str, Any]:
    return await _execute(service.delete_admin_record(resource, record_id))


@router.get("/services")
async def list_services(
    service: SeoManagementDependency,
    campaign_id: int | None = Query(default=None, gt=0),
    campaign_slug: str | None = None,
) -> list[dict[str, Any]]:
    return await _execute(service.list_services(campaign_id, campaign_slug))


@router.get("/pages")
async def list_pages(
    service: SeoManagementDependency,
    campaign_id: int | None = Query(default=None, gt=0),
    campaign_slug: str | None = None,
    page_type: Literal["home", "service", "service_city"] | None = None,
    limit: int = Query(default=300, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    return await _execute(
        service.list_pages(
            campaign_id=campaign_id,
            campaign_slug=campaign_slug,
            page_type=page_type,
            limit=limit,
            offset=offset,
        )
    )


@router.post("/pages", status_code=status.HTTP_201_CREATED)
async def create_page(
    payload: CampaignPageCreateRequest,
    service: SeoManagementDependency,
) -> dict[str, Any]:
    return await _execute(service.create_page(payload))


@router.put("/pages/{campaign_page_id}")
async def update_page(
    campaign_page_id: int,
    payload: CampaignPageUpdateRequest,
    service: SeoManagementDependency,
) -> dict[str, Any]:
    return await _execute(service.update_page(campaign_page_id, payload))


@router.get("/post-groups")
async def list_post_groups(
    service: SeoManagementDependency,
    campaign_id: int | None = Query(default=None, gt=0),
    state: str | None = None,
    post_status: Literal[
        "empty",
        "defined",
        "creating",
        "published",
        "failed",
    ]
    | None = None,
    search: str | None = None,
    limit: int = Query(default=500, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return await _execute(
        service.list_post_groups(
            campaign_id=campaign_id,
            state=state,
            post_status=post_status,
            search=search,
            limit=limit,
        )
    )


@router.post("/post-groups", status_code=status.HTTP_201_CREATED)
async def create_post_group(
    payload: PostGroupCreateRequest,
    service: SeoManagementDependency,
) -> dict[str, Any]:
    return await _execute(service.create_post_group(payload))


@router.put("/post-groups/{group_id}")
async def update_post_group(
    group_id: int,
    payload: PostGroupUpdateRequest,
    service: SeoManagementDependency,
) -> dict[str, Any]:
    return await _execute(service.update_post_group(group_id, payload))


@router.delete("/post-groups/{group_id}")
async def delete_post_group(
    group_id: int,
    service: SeoManagementDependency,
) -> dict[str, Any]:
    return await _execute(service.delete_post_group(group_id))


@router.post("/pages/{campaign_page_id}/rank-position")
async def check_rank_position(
    campaign_page_id: int,
    service: SeoManagementDependency,
) -> dict[str, Any]:
    return await _execute(service.check_rank_position(campaign_page_id))


@router.post("/pages/import-xlsx")
async def import_pages(
    payload: ImportPagesRequest,
    service: SeoManagementDependency,
) -> dict[str, Any]:
    return await _execute(service.import_pages(payload))


@router.get("/pages/import-template")
async def download_import_template() -> Response:
    return Response(
        content=build_import_template(),
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{IMPORT_TEMPLATE_FILENAME}"'
            )
        },
    )


@router.get("/execution-queue")
async def list_execution_queue(
    service: SeoManagementDependency,
    view: Literal["active", "history", "all"] = "all",
    campaign_id: int | None = Query(default=None, gt=0),
    campaign_page_id: int | None = Query(default=None, gt=0),
    page_type: Literal["home", "service", "service_city"] | None = None,
    limit: int = Query(default=150, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return await _execute(
        service.list_queue(
            view=view,
            campaign_id=campaign_id,
            campaign_page_id=campaign_page_id,
            page_type=page_type,
            limit=limit,
        )
    )


@router.post("/execution-queue/schedule")
async def schedule_pages(
    payload: SchedulePagesRequest,
    service: SeoManagementDependency,
) -> dict[str, Any]:
    return await _execute(service.schedule_pages(payload))


@router.post("/execution-queue/run-now")
async def run_now(
    payload: RunNowRequest,
    service: SeoManagementDependency,
) -> dict[str, Any]:
    return await _execute(service.run_now(payload))


@router.post("/execution-queue/run-daily-now")
async def run_daily_now(
    payload: RunDailyRequest,
    service: SeoManagementDependency,
) -> dict[str, Any]:
    return await _execute(service.run_daily(payload))


@router.post("/execution-queue/{queue_execution_id}/retry")
async def retry_queue(
    queue_execution_id: int,
    service: SeoManagementDependency,
    payload: RetryQueueRequest | None = None,
) -> dict[str, Any]:
    return await _execute(service.retry(queue_execution_id, payload))


@router.post("/execution-queue/{queue_execution_id}/cancel")
async def cancel_queue(
    queue_execution_id: int,
    service: SeoManagementDependency,
) -> dict[str, Any]:
    return await _execute(service.cancel(queue_execution_id))


async def _execute[T](awaitable: Awaitable[T]) -> T:
    try:
        return jsonable_encoder(await awaitable)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc) or exc.__class__.__name__,
        ) from exc
