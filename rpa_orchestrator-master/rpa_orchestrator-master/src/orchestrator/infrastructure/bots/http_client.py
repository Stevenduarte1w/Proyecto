from __future__ import annotations

from uuid import UUID

import httpx

from orchestrator.core.config import get_settings


class HttpBotClient:
    async def start_execution(self, base_url: str, flow_id: str, execution_id: UUID) -> None:
        settings = get_settings()
        payload = {"flow_id": flow_id, "execution_id": str(execution_id)}
        timeout = httpx.Timeout(settings.bot_request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{base_url}/executions", json=payload)
            response.raise_for_status()

