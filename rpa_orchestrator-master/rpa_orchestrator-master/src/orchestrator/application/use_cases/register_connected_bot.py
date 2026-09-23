from __future__ import annotations

from dataclasses import asdict
from uuid import uuid4

from orchestrator.application.dtos import BotRegisterMessage, BotResponse
from orchestrator.domain.entities import Bot
from orchestrator.domain.ports import BotPresenceRepository, BotRepository


class RegisterConnectedBot:
    def __init__(
        self,
        bot_repository: BotRepository,
        presence_repository: BotPresenceRepository,
        presence_ttl_seconds: int,
        heartbeat_deadline_seconds: int,
    ) -> None:
        self._bot_repository = bot_repository
        self._presence_repository = presence_repository
        self._presence_ttl_seconds = presence_ttl_seconds
        self._heartbeat_deadline_seconds = heartbeat_deadline_seconds

    async def execute(self, message: BotRegisterMessage) -> tuple[BotResponse, str]:
        existing = await self._bot_repository.get_by_key(message.bot_key)
        bot = existing or Bot(
            bot_key=message.bot_key,
            name=message.name,
            bot_type=message.bot_type,
        )
        bot.name = message.name
        bot.bot_type = message.bot_type
        bot.capabilities = message.capabilities
        bot.version = message.version
        bot.max_concurrency = message.max_concurrency
        bot.metadata = message.metadata
        bot.enabled = True
        bot.mark_seen()

        saved = await self._bot_repository.save(bot)
        session_id = str(uuid4())
        await self._presence_repository.mark_online(
            bot=saved,
            session_id=session_id,
            available_slots=message.available_slots,
            ttl_seconds=self._presence_ttl_seconds,
            deadline_seconds=self._heartbeat_deadline_seconds,
        )
        return BotResponse(**asdict(saved)), session_id
