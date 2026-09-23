from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from orchestrator.api.v1.dependencies import post_monitor_service
from orchestrator.api.v1.routes.post_monitor import (
    _valid_post_monitor_token,
    router,
)
from orchestrator.application.post_monitor import (
    PostMonitorEventReceipt,
    PostMonitorRunResultMessage,
)
from orchestrator.main import create_app


class FakePostMonitorService:
    def __init__(self) -> None:
        self.bot_id = uuid4()
        self.results: list[object] = []
        self.alerts: list[object] = []
        self.heartbeats: list[object] = []

    async def register(self, message: Any) -> dict[str, Any]:
        return {
            "id": self.bot_id,
            "bot_key": "post-monitor-01",
            "name": "Post Monitor",
            "enabled": True,
        }

    async def heartbeat(self, bot_id: UUID, message: Any) -> None:
        assert bot_id == self.bot_id
        self.heartbeats.append(message)

    async def ingest_result(
        self,
        bot_id: UUID,
        registered_bot_key: str,
        message: Any,
    ) -> PostMonitorEventReceipt:
        assert bot_id == self.bot_id
        assert registered_bot_key == "post-monitor-01"
        self.results.append(message)
        return PostMonitorEventReceipt(
            event_id=message.event_id,
            stored_at=datetime.now(UTC),
        )

    async def ingest_alert(
        self,
        bot_id: UUID,
        registered_bot_key: str,
        message: Any,
    ) -> PostMonitorEventReceipt:
        assert bot_id == self.bot_id
        assert registered_bot_key == "post-monitor-01"
        self.alerts.append(message)
        return PostMonitorEventReceipt(
            event_id=message.event_id,
            stored_at=datetime.now(UTC),
        )

    async def overview(self) -> dict[str, Any]:
        return {
            "bot": {"connection_status": "online"},
            "runs": {"last_24h": 1},
            "alerts": {"open": 1},
            "latest_metrics": {"score": 54.2},
        }

    async def list_runs(self, status: str | None, limit: int) -> list[dict[str, Any]]:
        return [{"run_id": str(uuid4()), "status": status or "succeeded", "limit": limit}]

    async def list_alerts(
        self,
        status: str | None,
        severity: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        return [
            {
                "alert_id": str(uuid4()),
                "status": status or "open",
                "severity": severity or "warning",
                "limit": limit,
            }
        ]

    async def update_alert(self, alert_id: UUID, status: str) -> dict[str, Any]:
        return {"alert_id": alert_id, "status": status}


def _registration() -> dict[str, Any]:
    return {
        "type": "post_monitor.register",
        "schema_version": "post-monitor.register.v1",
        "bot_key": "post-monitor-01",
        "name": "Post Monitor",
        "version": "1.0.0",
        "environment": "test",
    }


def _result() -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "type": "post_monitor.run.result",
        "schema_version": "post-monitor.result.v1",
        "event_id": str(uuid4()),
        "bot_key": "post-monitor-01",
        "occurred_at": now,
        "payload": {
            "run_id": str(uuid4()),
            "status": "succeeded",
            "started_at": now,
            "finished_at": now,
            "target": {"external_id": "post-123", "url": "https://example.com/post"},
            "metrics": {"score": 84.5},
            "result": {"changed": True},
        },
    }


def _alert() -> dict[str, Any]:
    return {
        "type": "post_monitor.threshold.alert",
        "schema_version": "post-monitor.alert.v1",
        "event_id": str(uuid4()),
        "bot_key": "post-monitor-01",
        "occurred_at": datetime.now(UTC).isoformat(),
        "payload": {
            "alert_id": str(uuid4()),
            "severity": "warning",
            "metric": "score",
            "observed_value": 54.2,
            "operator": "lt",
            "threshold": 60,
            "message": "Score below configured threshold",
            "rule": {"rule_id": "minimum-score"},
            "target": {"external_id": "post-123"},
        },
    }


def _app(service: FakePostMonitorService) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/post-monitor")
    app.dependency_overrides[post_monitor_service] = lambda: service
    return app


def test_independent_websocket_accepts_results_alerts_and_heartbeats() -> None:
    service = FakePostMonitorService()
    with TestClient(_app(service)) as client:
        with client.websocket_connect("/post-monitor/ws") as websocket:
            websocket.send_json(_registration())
            assert websocket.receive_json()["type"] == "post_monitor.registered"

            websocket.send_json(
                {
                    "type": "post_monitor.heartbeat",
                    "schema_version": "post-monitor.heartbeat.v1",
                    "status": "idle",
                    "current_jobs": 0,
                    "outbox_pending": 0,
                }
            )
            assert websocket.receive_json()["type"] == "post_monitor.heartbeat.ack"

            result = _result()
            websocket.send_json(result)
            result_ack = websocket.receive_json()
            assert result_ack["type"] == "post_monitor.event.ack"
            assert result_ack["event_id"] == result["event_id"]

            alert = _alert()
            websocket.send_json(alert)
            alert_ack = websocket.receive_json()
            assert alert_ack["type"] == "post_monitor.event.ack"
            assert alert_ack["event_id"] == alert["event_id"]

    assert len(service.heartbeats) == 1
    assert len(service.results) == 1
    assert len(service.alerts) == 1


def test_independent_websocket_rejects_main_workflow_messages() -> None:
    service = FakePostMonitorService()
    with TestClient(_app(service)) as client:
        with client.websocket_connect("/post-monitor/ws") as websocket:
            websocket.send_json(_registration())
            websocket.receive_json()
            websocket.send_json(
                {
                    "type": "execution.succeeded",
                    "execution_id": str(uuid4()),
                    "payload": {},
                }
            )
            response = websocket.receive_json()

    assert response["type"] == "post_monitor.error"
    assert response["code"] == "unsupported_message_type"
    assert service.results == []


def test_post_monitor_rest_endpoints_are_separate() -> None:
    service = FakePostMonitorService()
    with TestClient(_app(service)) as client:
        overview = client.get("/post-monitor/overview")
        runs = client.get("/post-monitor/runs?status=failed&limit=20")
        alerts = client.get("/post-monitor/alerts?status=open&severity=critical")
        alert_id = uuid4()
        updated = client.patch(
            f"/post-monitor/alerts/{alert_id}",
            json={"status": "acknowledged"},
        )

    assert overview.status_code == 200
    assert overview.json()["bot"]["connection_status"] == "online"
    assert runs.json()[0]["status"] == "failed"
    assert alerts.json()[0]["severity"] == "critical"
    assert updated.json() == {"alert_id": str(alert_id), "status": "acknowledged"}


def test_run_result_requires_valid_dates_and_contract() -> None:
    message = _result()
    message["payload"]["finished_at"] = "2026-09-04T10:00:00Z"
    message["payload"]["started_at"] = "2026-09-04T11:00:00Z"

    with pytest.raises(ValidationError):
        PostMonitorRunResultMessage.model_validate(message)


def test_post_monitor_token_validation() -> None:
    assert _valid_post_monitor_token("", "")
    assert _valid_post_monitor_token("Bearer secret", "secret")
    assert not _valid_post_monitor_token("Bearer wrong", "secret")
    assert not _valid_post_monitor_token("", "secret")


def test_post_monitor_routes_are_mounted_in_main_app() -> None:
    app = create_app()
    paths = app.openapi()["paths"]

    assert "/api/v1/post-monitor/overview" in paths
    assert "/api/v1/post-monitor/runs" in paths
    assert "/api/v1/post-monitor/alerts" in paths
    assert str(app.url_path_for("post_monitor_websocket")) == "/api/v1/post-monitor/ws"
