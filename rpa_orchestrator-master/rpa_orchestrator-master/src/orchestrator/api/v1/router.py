from __future__ import annotations

from fastapi import APIRouter

from orchestrator.api.v1.routes import (
    backlinks,
    bots,
    executions,
    flows,
    health,
    instagram,
    page_executions,
    post_bot,
    post_monitor,
    seo_management,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(backlinks.router, prefix="/backlinks", tags=["backlinks"])
api_router.include_router(bots.router, prefix="/bots", tags=["bots"])
api_router.include_router(flows.router, prefix="/flows", tags=["flows"])
api_router.include_router(executions.router, prefix="/executions", tags=["executions"])
api_router.include_router(
    instagram.router,
    prefix="/instagram",
    tags=["instagram"],
)
api_router.include_router(
    post_bot.router,
    prefix="/post-bot",
    tags=["post-bot"],
)
api_router.include_router(
    post_monitor.router,
    prefix="/post-monitor",
    tags=["post-monitor"],
)
api_router.include_router(
    page_executions.router,
    prefix="/page-executions",
    tags=["page-executions"],
)
api_router.include_router(
    seo_management.router,
    prefix="/seo",
    tags=["seo-management"],
)
