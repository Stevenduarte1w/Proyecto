from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from orchestrator.core.config import get_settings

_client: AsyncIOMotorClient[dict] | None = None


async def init_mongo() -> None:
    global _client
    settings = get_settings()
    _client = AsyncIOMotorClient(settings.mongo_dsn)
    await _client.admin.command("ping")
    database = _client[settings.mongo_database]
    await database["seo_page_executions"].create_index(
        "queue_execution_id",
        unique=True,
        name="uq_seo_page_executions_queue_execution_id",
    )
    await database["seo_page_executions"].create_index(
        [("campaign_id", 1), ("campaign_page_id", 1), ("started_at", -1)],
        name="ix_seo_page_executions_campaign_page_started",
    )
    await database["seo_page_execution_artifacts"].create_index(
        [("queue_execution_id", 1), ("filename", 1)],
        unique=True,
        name="uq_seo_page_execution_artifacts_execution_filename",
    )
    await database["seo_page_execution_artifacts"].create_index(
        [("campaign_id", 1), ("campaign_page_id", 1)],
        name="ix_seo_page_execution_artifacts_campaign_page",
    )


def get_mongo_database() -> AsyncIOMotorDatabase[dict]:
    if _client is None:
        raise RuntimeError("Mongo client has not been initialized")
    return _client[get_settings().mongo_database]


async def close_mongo() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
