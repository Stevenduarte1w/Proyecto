from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestrator.api.v1.dependencies import page_execution_service
from orchestrator.api.v1.routes.page_executions import router


class FakePageExecutionService:
    def __init__(self) -> None:
        self.last_payload: Any = "unset"

    async def store_artifact(
        self,
        queue_execution_id: int,
        filename: str,
        payload: Any,
    ) -> dict[str, Any]:
        self.last_payload = payload
        return {
            "queue_execution_id": queue_execution_id,
            "filename": filename,
            "payload": payload,
        }


def test_artifact_endpoint_accepts_dynamic_json_payload() -> None:
    service = FakePageExecutionService()
    app = FastAPI()
    app.include_router(router, prefix="/page-executions")
    app.dependency_overrides[page_execution_service] = lambda: service

    with TestClient(app) as client:
        response = client.put(
            "/page-executions/36/artifacts/dynamic.json",
            json=["dynamic", {"nested": True}],
        )

    assert response.status_code == 200
    assert response.json()["payload"] == ["dynamic", {"nested": True}]
    assert service.last_payload == ["dynamic", {"nested": True}]
