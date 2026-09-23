from __future__ import annotations

from dataclasses import asdict

from orchestrator.application.dtos import BotCreateRequest, BotResponse
from orchestrator.domain.entities import Bot
from orchestrator.domain.ports import BotRepository


class RegisterBot:
    def __init__(self, bot_repository: BotRepository) -> None:
        self._bot_repository = bot_repository

    async def execute(self, request: BotCreateRequest) -> BotResponse:
        bot = Bot(
            name=request.name,
            bot_key=request.bot_key,
            bot_type=request.bot_type,
            base_url=str(request.base_url).rstrip("/") if request.base_url else None,
            capabilities=request.capabilities,
            version=request.version,
            max_concurrency=request.max_concurrency,
            metadata=request.metadata,
            enabled=request.enabled,
        )
        saved = await self._bot_repository.save(bot)
        return BotResponse(**asdict(saved))
