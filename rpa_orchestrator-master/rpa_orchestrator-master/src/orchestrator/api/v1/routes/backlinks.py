from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.v1.auth import require_dashboard_operator
from orchestrator.api.v1.dependencies import db_session
from orchestrator.application.dtos import (
    BacklinksCatalogResponse,
    BotCatalogUpdatedMessage,
)
from orchestrator.domain.backlinks import BACKLINKS_CAPABILITY
from orchestrator.infrastructure.postgres.repositories import SqlAlchemyBotRepository
from orchestrator.infrastructure.redis.presence import RedisBotPresenceRepository

router = APIRouter(dependencies=[Depends(require_dashboard_operator)])


@router.get("/companies", response_model=BacklinksCatalogResponse)
async def list_backlinks_companies(
    session: AsyncSession = Depends(db_session),
) -> BacklinksCatalogResponse:
    bots = await SqlAlchemyBotRepository(session).list_enabled_by_capability(
        BACKLINKS_CAPABILITY
    )
    for bot in bots:
        try:
            catalog = BotCatalogUpdatedMessage.model_validate(
                {
                    "type": "bot.catalog.updated",
                    "catalog_version": bot.metadata.get("catalog_version"),
                    "companies": bot.metadata.get("companies"),
                }
            )
        except ValueError:
            continue
        return BacklinksCatalogResponse(
            bot_id=bot.id,
            bot_key=bot.bot_key,
            online=await RedisBotPresenceRepository().is_online(bot.id),
            catalog_version=catalog.catalog_version,
            companies=catalog.companies,
        )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="No SAAF company catalog is available",
    )
