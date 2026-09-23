from __future__ import annotations

from fastapi.testclient import TestClient

from orchestrator.main import create_app


def test_health_check() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

