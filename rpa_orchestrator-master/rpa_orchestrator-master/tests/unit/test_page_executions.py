from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from orchestrator.application.use_cases.page_executions import PageExecutionService
from orchestrator.domain.page_execution import SourcePageExecution


class InMemorySourceRepository:
    def __init__(self, execution: SourcePageExecution | None) -> None:
        self.execution = execution

    async def get(self, queue_execution_id: int) -> SourcePageExecution | None:
        if self.execution is None or self.execution.queue_execution_id != queue_execution_id:
            return None
        return self.execution


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self.execution: dict[str, Any] | None = None
        self.artifacts: dict[tuple[int, str], dict[str, Any]] = {}

    async def upsert_execution(
        self,
        execution: SourcePageExecution,
        log_key: str,
    ) -> dict[str, Any]:
        filenames = sorted(
            filename
            for queue_execution_id, filename in self.artifacts
            if queue_execution_id == execution.queue_execution_id
        )
        self.execution = {
            "queue_execution_id": execution.queue_execution_id,
            "campaign_id": execution.campaign_id,
            "campaign_name": execution.campaign_name,
            "campaign_page_id": execution.campaign_page_id,
            "page_slug": execution.page_slug,
            "redis_log_key": log_key,
            "artifacts": {"count": len(filenames), "filenames": filenames},
        }
        return deepcopy(self.execution)

    async def get_execution(self, queue_execution_id: int) -> dict[str, Any] | None:
        if self.execution is None:
            return None
        if self.execution["queue_execution_id"] != queue_execution_id:
            return None
        return deepcopy(self.execution)

    async def upsert_artifact(
        self,
        execution: SourcePageExecution,
        filename: str,
        payload: Any,
    ) -> dict[str, Any]:
        document = {
            "queue_execution_id": execution.queue_execution_id,
            "campaign_id": execution.campaign_id,
            "campaign_page_id": execution.campaign_page_id,
            "filename": filename,
            "payload": payload,
        }
        self.artifacts[(execution.queue_execution_id, filename)] = document
        await self.upsert_execution(
            execution,
            self.execution["redis_log_key"] if self.execution else "log-key",
        )
        return deepcopy(document)

    async def upsert_artifacts(
        self,
        execution: SourcePageExecution,
        artifacts: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            await self.upsert_artifact(execution, filename, payload)
            for filename, payload in artifacts.items()
        ]

    async def list_artifacts(self, queue_execution_id: int) -> list[dict[str, Any]]:
        return [
            deepcopy(document)
            for (execution_id, _), document in sorted(self.artifacts.items())
            if execution_id == queue_execution_id
        ]

    async def get_artifact(
        self,
        queue_execution_id: int,
        filename: str,
    ) -> dict[str, Any] | None:
        document = self.artifacts.get((queue_execution_id, filename))
        return deepcopy(document) if document else None

    async def list_campaigns(self) -> list[dict[str, Any]]:
        return []

    async def list_pages(self, campaign_id: int) -> list[dict[str, Any]]:
        return []

    async def list_page_executions(self, campaign_page_id: int) -> list[dict[str, Any]]:
        return []


class InMemoryLogRepository:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def set_log(
        self,
        execution: SourcePageExecution,
        payload: Any,
        ttl_seconds: int,
    ) -> dict[str, Any]:
        key = (
            f"seo:campaign:{execution.campaign_id}:page:{execution.campaign_page_id}:"
            "bot:log"
        )
        document = self.documents.setdefault(
            key,
            {
                "scope": "page",
                "queue_execution_id": execution.queue_execution_id,
                "payload": None,
                "ttl_seconds": ttl_seconds,
                "entries": [],
            },
        )
        entry = {
            "queue_execution_id": execution.queue_execution_id,
            "payload": payload,
            "created_at": "2026-07-14T00:00:00+00:00",
        }
        document["entries"].append(entry)
        document["payload"] = payload
        document["entry_count"] = len(document["entries"])
        self.documents[key] = document
        return deepcopy(document)

    async def get_log(self, log_key: str) -> dict[str, Any] | None:
        document = self.documents.get(log_key)
        return deepcopy(document) if document else None


@pytest.fixture
def source_execution() -> SourcePageExecution:
    return SourcePageExecution(
        queue_execution_id=36,
        campaign_page_id=15,
        campaign_id=1,
        campaign_name="Campaña principal",
        page_slug="amarres-de-amor-belmont-gardens-chicago",
        page_url="https://example.com/page",
        status="success",
    )


@pytest.fixture
def service(source_execution: SourcePageExecution) -> PageExecutionService:
    return PageExecutionService(
        source_repository=InMemorySourceRepository(source_execution),
        document_repository=InMemoryDocumentRepository(),
        log_repository=InMemoryLogRepository(),
        log_ttl_seconds=86400,
    )


async def test_syncs_page_execution_without_requiring_artifacts(
    service: PageExecutionService,
) -> None:
    result = await service.sync_execution(36)

    assert result["campaign_id"] == 1
    assert result["campaign_page_id"] == 15
    assert result["page_slug"] == "amarres-de-amor-belmont-gardens-chicago"
    assert result["artifacts"]["count"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"dynamic": {"field": [1, 2, 3]}},
        ["a", {"different": True}],
        "plain JSON string",
        42,
        True,
        None,
    ],
)
async def test_accepts_any_valid_json_payload(
    service: PageExecutionService,
    payload: Any,
) -> None:
    result = await service.store_artifact(36, "dynamic_result.json", payload)

    assert result["payload"] == payload


async def test_artifacts_are_upserted_by_execution_and_filename(
    service: PageExecutionService,
) -> None:
    await service.store_artifact(36, "support_post_1.json", {"version": 1})
    await service.store_artifact(36, "support_post_1.json", {"version": 2})

    artifacts = await service.list_artifacts(36)

    assert len(artifacts) == 1
    assert artifacts[0]["payload"] == {"version": 2}


async def test_bulk_upload_accepts_partial_and_additional_artifact_sets(
    service: PageExecutionService,
) -> None:
    result = await service.store_artifacts(
        36,
        {
            "auto_local_research.json": {"research": True},
            "unexpected_but_valid.json": ["dynamic"],
        },
    )

    assert result["stored_count"] == 2
    assert all("payload" not in item for item in result["items"])
    artifacts = await service.list_artifacts(36)
    assert len(artifacts) == 2


async def test_log_uses_campaign_page_and_execution_hierarchy(
    service: PageExecutionService,
) -> None:
    await service.sync_execution(36)
    await service.store_log(36, {"line": "Procesando pagina"})

    result = await service.get_log(36)

    assert result is not None
    assert result["scope"] == "page"
    assert result["payload"] == {"line": "Procesando pagina"}
    assert result["ttl_seconds"] == 86400


async def test_log_accumulates_entries_for_the_page(
    service: PageExecutionService,
) -> None:
    await service.sync_execution(36)
    await service.store_log(36, {"line": "Inicio"})
    await service.store_log(36, {"line": "PageSpeed terminado"})

    result = await service.get_log(36)

    assert result is not None
    assert result["entry_count"] == 2
    assert [entry["payload"]["line"] for entry in result["entries"]] == [
        "Inicio",
        "PageSpeed terminado",
    ]


async def test_rejects_non_json_filename(service: PageExecutionService) -> None:
    with pytest.raises(ValueError, match=r"\.json"):
        await service.store_artifact(36, "execution.log", {"value": 1})


async def test_missing_source_execution_is_reported() -> None:
    service = PageExecutionService(
        source_repository=InMemorySourceRepository(None),
        document_repository=InMemoryDocumentRepository(),
        log_repository=InMemoryLogRepository(),
        log_ttl_seconds=86400,
    )

    with pytest.raises(LookupError, match="36"):
        await service.sync_execution(36)

