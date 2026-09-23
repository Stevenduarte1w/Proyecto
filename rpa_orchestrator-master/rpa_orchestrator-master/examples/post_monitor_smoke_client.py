from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import websockets

WS_URL = os.getenv(
    "POST_MONITOR_WS_URL",
    "ws://localhost:8005/api/v1/post-monitor/ws",
)
BOT_TOKEN = os.getenv("POST_MONITOR_WS_TOKEN", "")
BOT_KEY = os.getenv("POST_MONITOR_BOT_KEY", "post-monitor-smoke-01")
SCORE = float(os.getenv("POST_MONITOR_SCORE", "54.2"))
THRESHOLD = float(os.getenv("POST_MONITOR_THRESHOLD", "60"))


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


async def send_event(websocket: Any, event: dict[str, Any]) -> None:
    await websocket.send(json.dumps(event))
    while True:
        response = json.loads(await websocket.recv())
        if response.get("type") == "post_monitor.heartbeat.ack":
            continue
        if response.get("type") == "post_monitor.error":
            raise RuntimeError(f"Event rejected: {response}")
        if response.get("type") != "post_monitor.event.ack":
            raise RuntimeError(f"Unexpected response: {response}")
        if response.get("event_id") != event["event_id"]:
            raise RuntimeError(f"ACK does not match event: {response}")
        print(json.dumps(response, indent=2))
        return


async def main() -> None:
    headers = {"Authorization": f"Bearer {BOT_TOKEN}"} if BOT_TOKEN else None
    async with websockets.connect(WS_URL, additional_headers=headers) as websocket:
        await websocket.send(
            json.dumps(
                {
                    "type": "post_monitor.register",
                    "schema_version": "post-monitor.register.v1",
                    "bot_key": BOT_KEY,
                    "name": "Post Monitor Smoke Client",
                    "version": "1.0.0",
                    "environment": "local",
                    "metadata": {"purpose": "integration-smoke-test"},
                }
            )
        )
        registration = json.loads(await websocket.recv())
        if registration.get("type") != "post_monitor.registered":
            raise RuntimeError(f"Registration failed: {registration}")
        print(json.dumps(registration, indent=2))

        run_id = str(uuid4())
        started_at = utc_now()
        finished_at = utc_now()
        result_event = {
            "type": "post_monitor.run.result",
            "schema_version": "post-monitor.result.v1",
            "event_id": str(uuid4()),
            "bot_key": BOT_KEY,
            "occurred_at": finished_at,
            "payload": {
                "run_id": run_id,
                "status": "succeeded",
                "started_at": started_at,
                "finished_at": finished_at,
                "target": {
                    "external_id": "smoke-post-01",
                    "url": "https://example.com/smoke-post",
                    "title": "Post de prueba",
                },
                "summary": "Ejecución de prueba completada",
                "metrics": {"score": SCORE},
                "result": {"smoke_test": True},
            },
        }
        await send_event(websocket, result_event)

        if SCORE < THRESHOLD:
            alert_event = {
                "type": "post_monitor.threshold.alert",
                "schema_version": "post-monitor.alert.v1",
                "event_id": str(uuid4()),
                "bot_key": BOT_KEY,
                "occurred_at": utc_now(),
                "payload": {
                    "alert_id": str(uuid4()),
                    "run_id": run_id,
                    "severity": "warning",
                    "metric": "score",
                    "observed_value": SCORE,
                    "operator": "lt",
                    "threshold": THRESHOLD,
                    "unit": "points",
                    "message": "El score bajó del umbral configurado por el bot",
                    "rule": {
                        "rule_id": "smoke-minimum-score",
                        "config_version": "1",
                        "configured_by": "post-bot",
                    },
                    "target": {
                        "external_id": "smoke-post-01",
                        "url": "https://example.com/smoke-post",
                        "title": "Post de prueba",
                    },
                },
            }
            await send_event(websocket, alert_event)


if __name__ == "__main__":
    asyncio.run(main())
