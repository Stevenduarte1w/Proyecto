from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import WebSocket


@dataclass(slots=True)
class BotConnection:
    session_id: str
    websocket: WebSocket


class BotWebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[UUID, BotConnection] = {}

    async def connect(self, bot_id: UUID, session_id: str, websocket: WebSocket) -> None:
        previous = self._connections.get(bot_id)
        self._connections[bot_id] = BotConnection(session_id=session_id, websocket=websocket)
        if previous is not None and previous.websocket is not websocket:
            await previous.websocket.close(code=1012, reason="Bot opened a newer session")

    async def disconnect(self, bot_id: UUID, session_id: str | None = None) -> None:
        current = self._connections.get(bot_id)
        if current is not None and (session_id is None or current.session_id == session_id):
            self._connections.pop(bot_id, None)

    def is_connected(self, bot_id: UUID) -> bool:
        return bot_id in self._connections

    async def send_execution(
        self,
        bot_id: UUID,
        flow_id: str,
        execution_id: UUID,
        capability: str,
        stage: str | None,
        input_document_id: str | None,
        command_payload: dict[str, Any] | None = None,
    ) -> None:
        connection = self._connections.get(bot_id)
        if connection is None:
            raise RuntimeError("Bot is not connected to this orchestrator instance")
        websocket = connection.websocket

        if capability == "indexing.submit":
            if command_payload is None:
                raise RuntimeError("Indexing command payload is required")
            await websocket.send_json(
                {
                    "type": "execution.start",
                    "bot_type": capability,
                    "stage": stage,
                    "flow_id": flow_id,
                    "execution_id": str(execution_id),
                    "campaign_page_id": command_payload["campaign_page_id"],
                    "payload": command_payload["payload"],
                }
            )
            return

        message: dict[str, Any] = {
            "type": "execution.run",
            "execution_id": str(execution_id),
            "flow_id": flow_id,
            "capability": capability,
            "stage": stage,
            "input_document_id": input_document_id,
            "input_url": f"/api/v1/executions/{execution_id}/input",
            "result_url": f"/api/v1/executions/{execution_id}/result",
        }
        if command_payload is not None:
            message["payload"] = command_payload
        await websocket.send_json(message)

    async def send_cancel(self, bot_id: UUID, execution_id: UUID) -> None:
        connection = self._connections.get(bot_id)
        if connection is None:
            raise RuntimeError("Bot is not connected to this orchestrator instance")
        await connection.websocket.send_json(
            {
                "type": "execution.cancel",
                "execution_id": str(execution_id),
            }
        )


bot_ws_manager = BotWebSocketManager()
