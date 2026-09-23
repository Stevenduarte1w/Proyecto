from __future__ import annotations

from typing import Any

from orchestrator.domain.page_execution import (
    SourcePageExecution,
    page_execution_history_log_key,
    page_execution_log_key,
)
from orchestrator.domain.ports import (
    PageExecutionDocumentRepository,
    PageExecutionLogRepository,
    SourcePageExecutionRepository,
)


class PageExecutionService:
    def __init__(
        self,
        source_repository: SourcePageExecutionRepository,
        document_repository: PageExecutionDocumentRepository,
        log_repository: PageExecutionLogRepository,
        log_ttl_seconds: int,
    ) -> None:
        self._source_repository = source_repository
        self._document_repository = document_repository
        self._log_repository = log_repository
        self._log_ttl_seconds = log_ttl_seconds

    async def sync_execution(self, queue_execution_id: int) -> dict[str, Any]:
        execution = await self._get_source_execution(queue_execution_id)
        return await self._document_repository.upsert_execution(
            execution,
            page_execution_log_key(execution),
        )

    async def store_artifact(
        self,
        queue_execution_id: int,
        filename: str,
        payload: Any,
    ) -> dict[str, Any]:
        normalized_filename = _normalize_json_filename(filename)
        execution = await self._get_or_sync_source_execution(queue_execution_id)
        return await self._document_repository.upsert_artifact(
            execution,
            normalized_filename,
            payload,
        )

    async def store_artifacts(
        self,
        queue_execution_id: int,
        artifacts: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_artifacts = {
            _normalize_json_filename(filename): payload
            for filename, payload in artifacts.items()
        }
        execution = await self._get_or_sync_source_execution(queue_execution_id)
        stored = await self._document_repository.upsert_artifacts(
            execution,
            normalized_artifacts,
        )
        return {
            "queue_execution_id": queue_execution_id,
            "stored_count": len(stored),
            "items": [_without_payload(document) for document in stored],
        }

    async def store_log(
        self,
        queue_execution_id: int,
        payload: Any,
    ) -> dict[str, Any]:
        execution = await self._get_or_sync_source_execution(queue_execution_id)
        return await self._log_repository.set_log(
            execution,
            payload,
            self._log_ttl_seconds,
        )

    async def get_execution(self, queue_execution_id: int) -> dict[str, Any] | None:
        return await self._document_repository.get_execution(queue_execution_id)

    async def link_orchestrator_flow(
        self,
        queue_execution_id: int,
        flow_id: str,
        execution_id: str,
    ) -> None:
        await self._document_repository.link_orchestrator_flow(
            queue_execution_id,
            flow_id,
            execution_id,
        )

    async def list_artifacts(self, queue_execution_id: int) -> list[dict[str, Any]]:
        await self._require_synced_execution(queue_execution_id)
        return await self._document_repository.list_artifacts(queue_execution_id)

    async def get_artifact(
        self,
        queue_execution_id: int,
        filename: str,
    ) -> dict[str, Any] | None:
        normalized_filename = _normalize_json_filename(filename)
        await self._require_synced_execution(queue_execution_id)
        return await self._document_repository.get_artifact(
            queue_execution_id,
            normalized_filename,
        )

    async def get_log(self, queue_execution_id: int) -> dict[str, Any] | None:
        execution = await self._require_synced_execution(queue_execution_id)
        source_execution = _source_execution_from_document(execution)
        history_log = await self._log_repository.get_log(
            page_execution_history_log_key(source_execution)
        )
        if history_log is not None:
            return history_log
        log_key = execution.get("redis_log_key")
        if not isinstance(log_key, str):
            return None
        return await self._log_repository.get_log(log_key)

    async def list_campaigns(self) -> list[dict[str, Any]]:
        return await self._document_repository.list_campaigns()

    async def list_pages(self, campaign_id: int) -> list[dict[str, Any]]:
        return await self._document_repository.list_pages(campaign_id)

    async def list_page_executions(self, campaign_page_id: int) -> list[dict[str, Any]]:
        return await self._document_repository.list_page_executions(campaign_page_id)

    async def _get_source_execution(
        self,
        queue_execution_id: int,
    ) -> SourcePageExecution:
        execution = await self._source_repository.get(queue_execution_id)
        if execution is None:
            raise LookupError(
                f"page_execution_queue record {queue_execution_id} was not found"
            )
        return execution

    async def _get_or_sync_source_execution(
        self,
        queue_execution_id: int,
    ) -> SourcePageExecution:
        document = await self._document_repository.get_execution(queue_execution_id)
        if document is not None:
            return _source_execution_from_document(document)
        execution = await self._get_source_execution(queue_execution_id)
        await self._document_repository.upsert_execution(
            execution,
            page_execution_log_key(execution),
        )
        return execution

    async def _require_synced_execution(
        self,
        queue_execution_id: int,
    ) -> dict[str, Any]:
        execution = await self._document_repository.get_execution(queue_execution_id)
        if execution is None:
            raise LookupError(f"Page execution {queue_execution_id} has not been synchronized")
        return execution


def _normalize_json_filename(filename: str) -> str:
    normalized = filename.strip()
    if (
        not normalized
        or len(normalized) > 255
        or "/" in normalized
        or "\\" in normalized
        or normalized in {".", ".."}
    ):
        raise ValueError("Artifact filename is invalid")
    if not normalized.lower().endswith(".json"):
        raise ValueError("Artifact filename must end in .json")
    return normalized


def _source_execution_from_document(document: dict[str, Any]) -> SourcePageExecution:
    return SourcePageExecution(
        queue_execution_id=int(document["queue_execution_id"]),
        campaign_page_id=int(document["campaign_page_id"]),
        campaign_id=int(document["campaign_id"]),
        campaign_name=str(document["campaign_name"]),
        page_slug=str(document["page_slug"]),
        page_url=document.get("page_url"),
        wp_page_id=document.get("wp_page_id"),
        trigger_type=document.get("trigger_type"),
        status=document.get("status"),
        scheduled_for=document.get("scheduled_for"),
        priority=document.get("priority"),
        attempts=document.get("attempts"),
        max_attempts=document.get("max_attempts"),
        started_at=document.get("started_at"),
        finished_at=document.get("finished_at"),
        log_path=document.get("log_path"),
        source_record=document.get("source_record", {}),
    )


def _without_payload(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "payload"}
