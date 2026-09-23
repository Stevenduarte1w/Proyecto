"""Conexiones WebSocket del bot de posts.

Es un gestor propio, separado de `bot_ws_manager`, para que el canal aislado no
comparta estado ni presupuesto de conexiones con el motor de workflows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from fastapi import WebSocket


@dataclass(slots=True)
class PostBotConnection:
    session_id: UUID
    websocket: WebSocket
    capabilities: list[str] = field(default_factory=list)


class PostBotWebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[UUID, PostBotConnection] = {}

    async def connect(
        self,
        worker_id: UUID,
        session_id: UUID,
        websocket: WebSocket,
        capabilities: list[str],
    ) -> None:
        previous = self._connections.get(worker_id)
        self._connections[worker_id] = PostBotConnection(
            session_id=session_id,
            websocket=websocket,
            capabilities=list(capabilities),
        )
        if previous is not None and previous.websocket is not websocket:
            await previous.websocket.close(code=1012, reason="Worker opened a newer session")

    async def disconnect(self, worker_id: UUID, session_id: UUID | None = None) -> None:
        current = self._connections.get(worker_id)
        if current is not None and (session_id is None or current.session_id == session_id):
            self._connections.pop(worker_id, None)

    def is_connected(self, worker_id: UUID) -> bool:
        return worker_id in self._connections

    def connected_worker_ids(self) -> list[UUID]:
        return list(self._connections)

    def capabilities_of(self, worker_id: UUID) -> list[str]:
        connection = self._connections.get(worker_id)
        return list(connection.capabilities) if connection is not None else []

    async def send_job(self, worker_id: UUID, job: dict[str, Any]) -> None:
        connection = self._connections.get(worker_id)
        if connection is None:
            raise RuntimeError("Post bot worker is not connected to this orchestrator instance")
        job_id = str(job["id"])
        await connection.websocket.send_json(
            {
                "type": "execution.run",
                "execution_id": job_id,
                "job_id": job_id,
                "flow_id": "",
                "capability": job["capability"],
                "stage": None,
                "input_url": f"/api/v1/post-bot/jobs/{job_id}/input",
                "result_url": f"/api/v1/post-bot/jobs/{job_id}",
                "payload": job.get("payload") or {},
            }
        )


post_bot_ws_manager = PostBotWebSocketManager()
