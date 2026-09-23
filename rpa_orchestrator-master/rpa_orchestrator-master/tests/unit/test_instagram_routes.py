from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestrator.api.v1.auth import require_dashboard_operator
from orchestrator.api.v1.dependencies import (
    get_instagram_execution_result_use_case,
    list_instagram_executions_use_case,
)
from orchestrator.api.v1.routes import instagram as instagram_routes
from orchestrator.api.v1.routes.instagram import router
from orchestrator.application.use_cases.instagram_executions import (
    GetInstagramExecutionResult,
    ListInstagramExecutions,
)
from orchestrator.core.config import Settings
from orchestrator.domain.entities import Execution, ExecutionStatus
from orchestrator.domain.instagram import (
    INSTAGRAM_MADURACION_CAPABILITY,
    INSTAGRAM_PROSPECTING_CAPABILITY,
)


class FakeExecutionRepository:
    def __init__(self, executions: list[Execution] | None = None) -> None:
        self.executions = list(executions or [])
        self.requested_capabilities: list[str] = []

    async def get(self, execution_id: UUID) -> Execution | None:
        return next((item for item in self.executions if item.id == execution_id), None)

    async def list_by_capabilities(
        self,
        capabilities: Sequence[str],
        *,
        execution_status: ExecutionStatus | None,
        limit: int,
    ) -> tuple[list[Execution], int]:
        self.requested_capabilities = list(capabilities)
        matches = [
            item for item in self.executions if item.requested_capability in set(capabilities)
        ]
        if execution_status is not None:
            matches = [item for item in matches if item.status is execution_status]
        return matches[:limit], len(matches)


class FakeDocumentRepository:
    def __init__(self, documents: dict[str, dict[str, Any]]) -> None:
        self.documents = documents

    async def get_document(self, document_id: str) -> dict[str, Any] | None:
        return self.documents.get(document_id)


def _execution(
    capability: str = INSTAGRAM_PROSPECTING_CAPABILITY,
    status: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    output_document_id: str | None = None,
) -> Execution:
    return Execution(
        flow_id=str(uuid4()),
        requested_capability=capability,
        status=status,
        output_document_id=output_document_id,
        created_at=datetime.now(UTC),
    )


def _client(
    *,
    listing: ListInstagramExecutions | None = None,
    result: GetInstagramExecutionResult | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/instagram")
    app.dependency_overrides[require_dashboard_operator] = lambda: None
    if listing is not None:
        app.dependency_overrides[list_instagram_executions_use_case] = lambda: listing
    if result is not None:
        app.dependency_overrides[get_instagram_execution_result_use_case] = lambda: result
    return TestClient(app)


def test_listing_is_restricted_to_instagram_capabilities() -> None:
    repository = FakeExecutionRepository(
        [
            _execution(INSTAGRAM_PROSPECTING_CAPABILITY),
            _execution(INSTAGRAM_MADURACION_CAPABILITY),
            _execution("wordpress.page_upsert"),
            _execution("seo.main"),
        ]
    )
    use_case = ListInstagramExecutions(execution_repository=repository)  # type: ignore[arg-type]

    with _client(listing=use_case) as client:
        response = client.get("/api/v1/instagram/executions")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    capabilities = {item["requested_capability"] for item in body["items"]}
    assert capabilities == {INSTAGRAM_PROSPECTING_CAPABILITY, INSTAGRAM_MADURACION_CAPABILITY}
    assert sorted(repository.requested_capabilities) == sorted(
        [INSTAGRAM_MADURACION_CAPABILITY, INSTAGRAM_PROSPECTING_CAPABILITY]
    )


def test_listing_hides_internal_execution_fields() -> None:
    repository = FakeExecutionRepository([_execution(output_document_id="out-1")])
    use_case = ListInstagramExecutions(execution_repository=repository)  # type: ignore[arg-type]

    with _client(listing=use_case) as client:
        response = client.get("/api/v1/instagram/executions")

    item = response.json()["items"][0]
    assert set(item) == {
        "id",
        "requested_capability",
        "status",
        "bot_id",
        "started_at",
        "completed_at",
        "created_at",
    }


def test_listing_rejects_a_capability_from_another_flow() -> None:
    repository = FakeExecutionRepository([_execution("seo.main")])
    use_case = ListInstagramExecutions(execution_repository=repository)  # type: ignore[arg-type]

    with _client(listing=use_case) as client:
        response = client.get("/api/v1/instagram/executions?capability=seo.main")

    assert response.status_code == 422
    assert repository.requested_capabilities == []


def test_listing_rejects_an_out_of_range_limit() -> None:
    repository = FakeExecutionRepository([])
    use_case = ListInstagramExecutions(execution_repository=repository)  # type: ignore[arg-type]

    with _client(listing=use_case) as client:
        response = client.get("/api/v1/instagram/executions?limit=500")

    assert response.status_code == 422


def test_result_returns_only_the_document_payload() -> None:
    execution = _execution(output_document_id="out-1")
    documents = FakeDocumentRepository(
        {
            "out-1": {
                "_id": "out-1",
                "flow_id": execution.flow_id,
                "payload": {"ok": True, "totals": {"created": 3}},
            }
        }
    )
    use_case = GetInstagramExecutionResult(
        execution_repository=FakeExecutionRepository([execution]),  # type: ignore[arg-type]
        flow_document_repository=documents,  # type: ignore[arg-type]
    )

    with _client(result=use_case) as client:
        response = client.get(f"/api/v1/instagram/executions/{execution.id}/result")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "totals": {"created": 3}}


def test_result_of_an_execution_from_another_flow_is_not_found() -> None:
    execution = _execution("wordpress.page_upsert", output_document_id="out-1")
    documents = FakeDocumentRepository({"out-1": {"payload": {"secret": True}}})
    use_case = GetInstagramExecutionResult(
        execution_repository=FakeExecutionRepository([execution]),  # type: ignore[arg-type]
        flow_document_repository=documents,  # type: ignore[arg-type]
    )

    with _client(result=use_case) as client:
        response = client.get(f"/api/v1/instagram/executions/{execution.id}/result")

    assert response.status_code == 404


@pytest.mark.parametrize(
    "status",
    [
        ExecutionStatus.PENDING,
        ExecutionStatus.QUEUED,
        ExecutionStatus.RUNNING,
        ExecutionStatus.CANCELLING,
    ],
)
def test_result_of_an_in_flight_execution_is_a_conflict(status: ExecutionStatus) -> None:
    execution = _execution(status=status)
    use_case = GetInstagramExecutionResult(
        execution_repository=FakeExecutionRepository([execution]),  # type: ignore[arg-type]
        flow_document_repository=FakeDocumentRepository({}),  # type: ignore[arg-type]
    )

    with _client(result=use_case) as client:
        response = client.get(f"/api/v1/instagram/executions/{execution.id}/result")

    assert response.status_code == 409


def test_result_of_a_finished_execution_without_document_is_not_found() -> None:
    execution = _execution(status=ExecutionStatus.FAILED)
    use_case = GetInstagramExecutionResult(
        execution_repository=FakeExecutionRepository([execution]),  # type: ignore[arg-type]
        flow_document_repository=FakeDocumentRepository({}),  # type: ignore[arg-type]
    )

    with _client(result=use_case) as client:
        response = client.get(f"/api/v1/instagram/executions/{execution.id}/result")

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("backend_url", "backend_token"),
    [("", ""), ("http://backend:8004", ""), ("", "token")],
)
def test_catalog_requires_backend_configuration(
    monkeypatch: pytest.MonkeyPatch,
    backend_url: str,
    backend_token: str,
) -> None:
    settings = Settings(
        instagram_backend_url=backend_url,
        instagram_backend_token=backend_token,
    )
    monkeypatch.setattr(instagram_routes, "get_settings", lambda: settings)

    with _client() as client:
        response = client.get("/api/v1/instagram/catalog")

    assert response.status_code == 503
