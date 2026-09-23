from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import websockets

ORCHESTRATOR_WS_URL = os.getenv(
    "ORCHESTRATOR_WS_URL",
    "ws://localhost:8005/api/v1/bots/ws",
)
BOT_TOKEN = os.getenv("BOT_TOKEN", "replace-with-worker-token")


async def send_heartbeat(websocket: websockets.ClientConnection) -> None:
    while True:
        await asyncio.sleep(25)
        await websocket.send(
            json.dumps(
                {
                    "type": "bot.heartbeat",
                    "current_jobs": 0,
                    "available_slots": 1,
                }
            )
        )


async def handle_execution(websocket: websockets.ClientConnection, message: dict[str, Any]) -> None:
    execution_id = message["execution_id"]
    stage = message["stage"]
    input_url = message["input_url"]

    try:
        # En un bot real, consulta input_url en la API REST del orquestador
        # antes de ejecutar la automatizacion.
        print(f"Execution {execution_id} stage={stage} input available at {input_url}")
        await asyncio.sleep(2)
        await websocket.send(
            json.dumps(
                {
                    "type": "execution.succeeded",
                    "execution_id": execution_id,
                    "payload": {"summary": "Example bot finished successfully"},
                }
            )
        )
    except Exception as exc:
        await websocket.send(
            json.dumps(
                {
                    "type": "execution.failed",
                    "execution_id": execution_id,
                    "error": str(exc),
                }
            )
        )


async def main() -> None:
    async with websockets.connect(
        ORCHESTRATOR_WS_URL,
        additional_headers={"Authorization": f"Bearer {BOT_TOKEN}"},
    ) as websocket:
        await websocket.send(
            json.dumps(
                {
                    "type": "bot.register",
                    "bot_key": "seo-audit-worker-01",
                    "name": "SEO Audit Worker 01",
                    "bot_type": "seo_audit",
                    "capabilities": ["seo.audit", "seo.technical"],
                    "version": "1.0.0",
                    "max_concurrency": 1,
                    "available_slots": 1,
                    "active_executions": [],
                    "metadata": {"runtime": "python"},
                }
            )
        )
        print(await websocket.recv())

        heartbeat_task = asyncio.create_task(send_heartbeat(websocket))
        try:
            async for raw_message in websocket:
                message = json.loads(raw_message)
                if message.get("type") == "execution.run":
                    await handle_execution(websocket, message)
                else:
                    print(message)
        finally:
            heartbeat_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
