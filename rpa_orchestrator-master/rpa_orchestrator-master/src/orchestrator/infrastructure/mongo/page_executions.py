from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from orchestrator.domain.page_execution import (
    REFERENCE_ARTIFACT_FILENAMES,
    SourcePageExecution,
)
from orchestrator.infrastructure.mongo.client import get_mongo_database


class MongoPageExecutionRepository:
    execution_collection_name = "seo_page_executions"
    artifact_collection_name = "seo_page_execution_artifacts"

    async def upsert_execution(
        self,
        execution: SourcePageExecution,
        log_key: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        update = {
            "queue_execution_id": execution.queue_execution_id,
            "campaign_id": execution.campaign_id,
            "campaign_name": execution.campaign_name,
            "campaign_page_id": execution.campaign_page_id,
            "page_slug": execution.page_slug,
            "page_url": execution.page_url,
            "wp_page_id": execution.wp_page_id,
            "trigger_type": execution.trigger_type,
            "status": execution.status,
            "scheduled_for": _mongo_safe(execution.scheduled_for),
            "priority": execution.priority,
            "attempts": execution.attempts,
            "max_attempts": execution.max_attempts,
            "started_at": execution.started_at,
            "finished_at": execution.finished_at,
            "log_path": execution.log_path,
            "redis_log_key": log_key,
            "source_database": "seo_agent_deep_seek",
            "source_record": _mongo_safe(execution.source_record),
            "synced_at": now,
        }
        collection = get_mongo_database()[self.execution_collection_name]
        await collection.update_one(
            {"queue_execution_id": execution.queue_execution_id},
            {
                "$set": update,
                "$setOnInsert": {
                    "created_at": now,
                    "artifacts": _artifact_summary([]),
                },
            },
            upsert=True,
        )
        document = await collection.find_one(
            {"queue_execution_id": execution.queue_execution_id}
        )
        if document is None:
            raise RuntimeError("Page execution was not persisted")
        return _serialize_document(document)

    async def get_execution(self, queue_execution_id: int) -> dict[str, Any] | None:
        document = await get_mongo_database()[self.execution_collection_name].find_one(
            {"queue_execution_id": queue_execution_id}
        )
        return _serialize_document(document) if document is not None else None

    async def link_orchestrator_flow(
        self,
        queue_execution_id: int,
        flow_id: str,
        execution_id: str,
    ) -> None:
        await get_mongo_database()[self.execution_collection_name].update_one(
            {"queue_execution_id": queue_execution_id},
            {
                "$set": {
                    "orchestrator_flow_id": flow_id,
                    "orchestrator_initial_execution_id": execution_id,
                    "synced_at": datetime.now(UTC),
                }
            },
        )

    async def upsert_artifact(
        self,
        execution: SourcePageExecution,
        filename: str,
        payload: Any,
    ) -> dict[str, Any]:
        document = await self._upsert_artifact(execution, filename, payload)
        await self._refresh_artifact_summary(execution.queue_execution_id)
        return document

    async def upsert_artifacts(
        self,
        execution: SourcePageExecution,
        artifacts: dict[str, Any],
    ) -> list[dict[str, Any]]:
        documents = [
            await self._upsert_artifact(execution, filename, payload)
            for filename, payload in artifacts.items()
        ]
        await self._refresh_artifact_summary(execution.queue_execution_id)
        return documents

    async def _upsert_artifact(
        self,
        execution: SourcePageExecution,
        filename: str,
        payload: Any,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        try:
            display_order = REFERENCE_ARTIFACT_FILENAMES.index(filename) + 1
        except ValueError:
            display_order = 1000
        collection = get_mongo_database()[self.artifact_collection_name]
        await collection.update_one(
            {
                "queue_execution_id": execution.queue_execution_id,
                "filename": filename,
            },
            {
                "$set": {
                    "campaign_id": execution.campaign_id,
                    "campaign_name": execution.campaign_name,
                    "campaign_page_id": execution.campaign_page_id,
                    "page_slug": execution.page_slug,
                    "page_url": execution.page_url,
                    "display_order": display_order,
                    "reference_artifact": display_order < 1000,
                    "payload": payload,
                    "size_bytes": _json_size(payload),
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "queue_execution_id": execution.queue_execution_id,
                    "filename": filename,
                    "created_at": now,
                },
            },
            upsert=True,
        )
        document = await collection.find_one(
            {
                "queue_execution_id": execution.queue_execution_id,
                "filename": filename,
            }
        )
        if document is None:
            raise RuntimeError("Page execution artifact was not persisted")
        return _serialize_document(document)

    async def list_artifacts(self, queue_execution_id: int) -> list[dict[str, Any]]:
        cursor = (
            get_mongo_database()[self.artifact_collection_name]
            .find(
                {"queue_execution_id": queue_execution_id},
                {"payload": 0},
            )
            .sort([("display_order", 1), ("filename", 1)])
        )
        return [_serialize_document(document) async for document in cursor]

    async def get_artifact(
        self,
        queue_execution_id: int,
        filename: str,
    ) -> dict[str, Any] | None:
        document = await get_mongo_database()[self.artifact_collection_name].find_one(
            {
                "queue_execution_id": queue_execution_id,
                "filename": filename,
            }
        )
        return _serialize_document(document) if document is not None else None

    async def list_campaigns(self) -> list[dict[str, Any]]:
        pipeline: list[dict[str, Any]] = [
            {
                "$group": {
                    "_id": "$campaign_id",
                    "name": {"$last": "$campaign_name"},
                    "page_ids": {"$addToSet": "$campaign_page_id"},
                    "execution_count": {"$sum": 1},
                    "last_execution_at": {"$max": "$started_at"},
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "campaign_id": "$_id",
                    "name": 1,
                    "page_count": {"$size": "$page_ids"},
                    "execution_count": 1,
                    "last_execution_at": 1,
                }
            },
            {"$sort": {"name": 1}},
        ]
        cursor = get_mongo_database()[self.execution_collection_name].aggregate(pipeline)
        return [document async for document in cursor]

    async def list_pages(self, campaign_id: int) -> list[dict[str, Any]]:
        pipeline: list[dict[str, Any]] = [
            {"$match": {"campaign_id": campaign_id}},
            {"$sort": {"started_at": 1, "queue_execution_id": 1}},
            {
                "$group": {
                    "_id": "$campaign_page_id",
                    "slug": {"$last": "$page_slug"},
                    "url": {"$last": "$page_url"},
                    "wp_page_id": {"$last": "$wp_page_id"},
                    "execution_count": {"$sum": 1},
                    "last_execution_at": {"$max": "$started_at"},
                    "last_status": {"$last": "$status"},
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "campaign_page_id": "$_id",
                    "slug": 1,
                    "url": 1,
                    "wp_page_id": 1,
                    "execution_count": 1,
                    "last_execution_at": 1,
                    "last_status": 1,
                }
            },
            {"$sort": {"slug": 1}},
        ]
        cursor = get_mongo_database()[self.execution_collection_name].aggregate(pipeline)
        return [document async for document in cursor]

    async def list_page_executions(self, campaign_page_id: int) -> list[dict[str, Any]]:
        cursor = (
            get_mongo_database()[self.execution_collection_name]
            .find({"campaign_page_id": campaign_page_id})
            .sort([("started_at", -1), ("queue_execution_id", -1)])
        )
        return [_serialize_document(document) async for document in cursor]

    async def _refresh_artifact_summary(self, queue_execution_id: int) -> None:
        cursor = get_mongo_database()[self.artifact_collection_name].find(
            {"queue_execution_id": queue_execution_id},
            {"filename": 1, "_id": 0},
        )
        filenames = [
            document["filename"]
            async for document in cursor
            if isinstance(document.get("filename"), str)
        ]
        filenames.sort()
        await get_mongo_database()[self.execution_collection_name].update_one(
            {"queue_execution_id": queue_execution_id},
            {
                "$set": {
                    "artifacts": _artifact_summary(filenames),
                    "synced_at": datetime.now(UTC),
                }
            },
        )


def _artifact_summary(filenames: list[str]) -> dict[str, Any]:
    found_reference = [
        filename for filename in REFERENCE_ARTIFACT_FILENAMES if filename in filenames
    ]
    missing_reference = [
        filename for filename in REFERENCE_ARTIFACT_FILENAMES if filename not in filenames
    ]
    return {
        "count": len(filenames),
        "filenames": filenames,
        "reference_expected_count": len(REFERENCE_ARTIFACT_FILENAMES),
        "reference_found_count": len(found_reference),
        "reference_missing": missing_reference,
    }


def _serialize_document(document: dict[str, Any]) -> dict[str, Any]:
    serialized = dict(document)
    if "_id" in serialized:
        serialized["_id"] = str(serialized["_id"])
    return serialized


def _mongo_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool | datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    if isinstance(value, Decimal | UUID | Enum):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _mongo_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_mongo_safe(item) for item in value]
    return str(value)


def _json_size(payload: Any) -> int:
    import json

    return len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
