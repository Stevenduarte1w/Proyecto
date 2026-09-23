from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from orchestrator.domain.page_execution import (
    SourcePageExecution,
    page_execution_history_log_key,
    page_execution_log_key,
)
from orchestrator.infrastructure.redis.client import get_redis


class RedisPageExecutionLogRepository:
    async def set_log(
        self,
        execution: SourcePageExecution,
        payload: Any,
        ttl_seconds: int,
    ) -> dict[str, Any]:
        written_at = datetime.now(UTC).isoformat()
        entry = {
            "queue_execution_id": execution.queue_execution_id,
            "status": execution.status,
            "payload": payload,
            "created_at": written_at,
        }
        document = await _append_log_entry(
            page_execution_log_key(execution),
            _base_document(execution, "execution"),
            entry,
            ttl_seconds,
        )
        await _append_log_entry(
            page_execution_history_log_key(execution),
            _base_document(execution, "page"),
            entry,
            ttl_seconds,
        )
        return document

    async def get_log(self, log_key: str) -> dict[str, Any] | None:
        raw = await get_redis().get(log_key)
        if raw is None:
            return None
        return _normalize_document(json.loads(raw))


async def _append_log_entry(
    log_key: str,
    base_document: dict[str, Any],
    entry: dict[str, Any],
    ttl_seconds: int,
) -> dict[str, Any]:
    raw = await get_redis().get(log_key)
    document = _normalize_document(json.loads(raw)) if raw is not None else base_document
    entries = document.setdefault("entries", [])
    if not isinstance(entries, list):
        entries = []
        document["entries"] = entries
    entries.append(entry)
    document["payload"] = entry["payload"]
    document["entry_count"] = len(entries)
    document["updated_at"] = entry["created_at"]
    await get_redis().set(
        log_key,
        json.dumps(document, ensure_ascii=False, separators=(",", ":")),
        ex=ttl_seconds,
    )
    return document


def _base_document(execution: SourcePageExecution, scope: str) -> dict[str, Any]:
    return {
        "scope": scope,
        "queue_execution_id": execution.queue_execution_id,
        "campaign_id": execution.campaign_id,
        "campaign_name": execution.campaign_name,
        "campaign_page_id": execution.campaign_page_id,
        "page_slug": execution.page_slug,
        "status": execution.status,
        "log_path": execution.log_path,
        "entries": [],
    }


def _normalize_document(document: dict[str, Any]) -> dict[str, Any]:
    entries = document.get("entries")
    if isinstance(entries, list):
        document["entry_count"] = len(entries)
        return document

    if "payload" in document:
        document["entries"] = [
            {
                "queue_execution_id": document.get("queue_execution_id"),
                "status": document.get("status"),
                "payload": document.get("payload"),
                "created_at": document.get("updated_at"),
            }
        ]
    else:
        document["entries"] = []
    document["entry_count"] = len(document["entries"])
    return document
