from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from orchestrator.domain.entities import Bot
from orchestrator.infrastructure.redis.client import get_redis

HEARTBEAT_DEADLINES_KEY = "bots:heartbeat_deadlines"

_RESERVE_SLOT_LUA = """
if redis.call('EXISTS', KEYS[3]) == 0 then
  return 0
end
if redis.call('SISMEMBER', KEYS[1], ARGV[1]) == 1 then
  return 1
end
local reserved = redis.call('SCARD', KEYS[1])
local reported = tonumber(redis.call('GET', KEYS[2]) or '0')
local capacity = math.min(reported, tonumber(ARGV[2]) - reserved)
if capacity <= 0 then
  return 0
end
redis.call('SADD', KEYS[1], ARGV[1])
return 1
"""

_CLAIM_EXPIRED_SESSION_LUA = """
local score = redis.call('ZSCORE', KEYS[1], ARGV[1])
if score and tonumber(score) <= tonumber(ARGV[2]) then
  redis.call('ZREM', KEYS[1], ARGV[1])
  return 1
end
return 0
"""

_MARK_OFFLINE_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 1
end
if ARGV[1] ~= '' then
  local payload = cjson.decode(raw)
  if payload['session_id'] ~= ARGV[1] then
    return 0
  end
end
redis.call('DEL', KEYS[1])
redis.call('DEL', KEYS[2])
return 1
"""

_HEARTBEAT_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 0
end
local payload = cjson.decode(raw)
if payload['session_id'] ~= ARGV[1] then
  return 0
end
payload['available_slots'] = tonumber(ARGV[2])
payload['current_jobs'] = tonumber(ARGV[3])
payload['last_heartbeat_at'] = ARGV[4]
redis.call('SET', KEYS[1], cjson.encode(payload), 'EX', ARGV[5])
redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[5])
redis.call('ZADD', KEYS[3], ARGV[7], ARGV[6])
return 1
"""


class RedisBotPresenceRepository:
    async def mark_online(
        self,
        bot: Bot,
        session_id: str,
        available_slots: int,
        ttl_seconds: int,
        deadline_seconds: int,
    ) -> None:
        now = datetime.now(UTC)
        payload = {
            "bot_id": str(bot.id),
            "bot_key": bot.bot_key,
            "bot_type": bot.bot_type,
            "capabilities": bot.capabilities,
            "session_id": session_id,
            "available_slots": available_slots,
            "current_jobs": 0,
            "connected_at": now.isoformat(),
            "last_heartbeat_at": now.isoformat(),
        }
        redis = get_redis()
        async with redis.pipeline(transaction=True) as pipe:
            pipe.set(_presence_key(bot.id), json.dumps(payload), ex=ttl_seconds)
            pipe.set(_reported_slots_key(bot.id), available_slots, ex=ttl_seconds)
            pipe.zadd(
                HEARTBEAT_DEADLINES_KEY,
                {_session_member(bot.id, session_id): now.timestamp() + deadline_seconds},
            )
            for capability in bot.capabilities:
                pipe.sadd(_capability_key(capability), str(bot.id))
                pipe.expire(_capability_key(capability), ttl_seconds)
            await pipe.execute()

    async def heartbeat(
        self,
        bot_id: UUID,
        available_slots: int,
        current_jobs: int,
        ttl_seconds: int,
        session_id: str,
        deadline_seconds: int,
    ) -> bool:
        redis = get_redis()
        now = datetime.now(UTC)
        result = await redis.eval(
            _HEARTBEAT_LUA,
            3,
            _presence_key(bot_id),
            _reported_slots_key(bot_id),
            HEARTBEAT_DEADLINES_KEY,
            session_id,
            str(available_slots),
            str(current_jobs),
            now.isoformat(),
            str(ttl_seconds),
            _session_member(bot_id, session_id),
            str(now.timestamp() + deadline_seconds),
        )
        return bool(result)

    async def mark_offline(self, bot_id: UUID, session_id: str | None = None) -> bool:
        result = await get_redis().eval(
            _MARK_OFFLINE_LUA,
            2,
            _presence_key(bot_id),
            _reported_slots_key(bot_id),
            session_id or "",
        )
        return bool(result)

    async def is_online(self, bot_id: UUID) -> bool:
        return bool(await get_redis().exists(_presence_key(bot_id)))

    async def available_slots(self, bot_id: UUID) -> int | None:
        raw = await get_redis().get(_reported_slots_key(bot_id))
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    async def reserve_slot(
        self,
        bot_id: UUID,
        execution_id: UUID,
        max_concurrency: int,
    ) -> bool:
        result = await get_redis().eval(
            _RESERVE_SLOT_LUA,
            3,
            _reserved_executions_key(bot_id),
            _reported_slots_key(bot_id),
            _presence_key(bot_id),
            str(execution_id),
            max_concurrency,
        )
        return bool(result)

    async def restore_reservation(self, bot_id: UUID, execution_id: UUID) -> None:
        await get_redis().sadd(_reserved_executions_key(bot_id), str(execution_id))

    async def release_slot(self, bot_id: UUID, execution_id: UUID) -> None:
        await get_redis().srem(_reserved_executions_key(bot_id), str(execution_id))

    async def current_session_id(self, bot_id: UUID) -> str | None:
        raw = await get_redis().get(_presence_key(bot_id))
        if raw is None:
            return None
        value = json.loads(raw).get("session_id")
        return value if isinstance(value, str) else None

    async def expired_sessions(self, now_timestamp: float) -> list[str]:
        values = await get_redis().zrangebyscore(
            HEARTBEAT_DEADLINES_KEY,
            "-inf",
            now_timestamp,
        )
        return [str(value) for value in values]

    async def claim_expired_session(self, member: str, now_timestamp: float) -> bool:
        result = await get_redis().eval(
            _CLAIM_EXPIRED_SESSION_LUA,
            1,
            HEARTBEAT_DEADLINES_KEY,
            member,
            now_timestamp,
        )
        return bool(result)

    async def reserved_execution_ids(self, bot_id: UUID) -> set[UUID]:
        values = await get_redis().smembers(_reserved_executions_key(bot_id))
        result: set[UUID] = set()
        for value in values:
            try:
                result.add(UUID(str(value)))
            except ValueError:
                continue
        return result

    async def bots_with_reservations(self) -> set[UUID]:
        redis = get_redis()
        result: set[UUID] = set()
        async for key in redis.scan_iter(match="bot:*:reserved_executions"):
            parts = str(key).split(":")
            if len(parts) != 3:
                continue
            try:
                result.add(UUID(parts[1]))
            except ValueError:
                continue
        return result


def _presence_key(bot_id: UUID) -> str:
    return f"bots:presence:{bot_id}"


def _capability_key(capability: str) -> str:
    return f"bots:capability:{capability}"


def _reported_slots_key(bot_id: UUID) -> str:
    return f"bot:{bot_id}:reported_available_slots"


def _reserved_executions_key(bot_id: UUID) -> str:
    return f"bot:{bot_id}:reserved_executions"


def _session_member(bot_id: UUID, session_id: str) -> str:
    return f"{bot_id}:{session_id}"
