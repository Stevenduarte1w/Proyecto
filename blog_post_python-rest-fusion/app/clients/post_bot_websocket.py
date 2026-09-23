"""Worker client for the orchestrator's isolated post-bot WebSocket queue."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
import websockets

logger = logging.getLogger(__name__)


class PostBotWebSocketWorker:
    """Connect, accept post jobs, delegate to the bot's REST ingress, and ACK."""

    def __init__(self) -> None:
        self.url = os.getenv(
            "POST_BOT_WS_URL", "ws://localhost:8005/api/v1/post-bot/ws"
        ).strip()
        self.token = os.getenv("POST_BOT_WS_TOKEN", "").strip()
        self.bot_key = os.getenv("POST_BOT_BOT_KEY", "post-bot-prod-01").strip()
        self.name = os.getenv("POST_BOT_NAME", "AI WordPress Post Bot").strip()
        self.callback_url = os.getenv(
            "POST_BOT_CALLBACK_URL", "http://127.0.0.1:8000/api/orchestrator/jobs"
        ).strip()
        self.capabilities = ["posts.create", "posts.optimize"]
        self._active: dict[str, asyncio.Task[None] | None] = {}
        self._pending_results: dict[str, dict[str, Any]] = {}
        self._send_lock = asyncio.Lock()
        self._websocket: Any = None

    async def run_forever(self, stop: asyncio.Event) -> None:
        if not self.token:
            raise RuntimeError("POST_BOT_WS_TOKEN es obligatorio para conectarse al orquestador")
        attempt = 0
        while not stop.is_set():
            heartbeat: asyncio.Task[None] | None = None
            try:
                logger.info("Connecting post bot to orchestrator WebSocket %s", self.url)
                async with websockets.connect(
                    self.url,
                    additional_headers={"Authorization": f"Bearer {self.token}"},
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=262144,
                ) as websocket:
                    self._websocket = websocket
                    await websocket.send(json.dumps({
                        "type": "bot.register",
                        "bot_key": self.bot_key,
                        "name": self.name,
                        "bot_type": "create_post",
                        "capabilities": self.capabilities,
                        "version": "3.1.0",
                        "max_concurrency": 1,
                        "available_slots": 1 if not self._active else 0,
                        "active_jobs": list(self._active),
                        "metadata": {"runtime": "python", "publisher": "wordpress-rest"},
                    }))
                    registered = json.loads(await asyncio.wait_for(websocket.recv(), timeout=15))
                    if registered.get("type") != "bot.registered":
                        raise RuntimeError(f"Orquestador rechazó el registro: {registered}")
                    logger.info("Post bot registered; recovered jobs=%s", registered.get("requeued_jobs", []))
                    attempt = 0
                    for execution_id, result in list(self._pending_results.items()):
                        await self._send_result(execution_id, result)
                    heartbeat = asyncio.create_task(self._heartbeat_loop(websocket))
                    async for frame in websocket:
                        try:
                            message = json.loads(frame)
                        except (TypeError, json.JSONDecodeError):
                            logger.warning("Ignoring invalid JSON from post-bot WebSocket")
                            continue
                        await self._handle_message(websocket, message)
            except asyncio.CancelledError:
                raise
            except Exception:
                attempt += 1
                logger.exception("Post-bot WebSocket disconnected; reconnect attempt %s", attempt)
            finally:
                if heartbeat:
                    heartbeat.cancel()
                    await asyncio.gather(heartbeat, return_exceptions=True)
                self._websocket = None
            if not stop.is_set():
                delay = min(30.0, 1.5 * (2 ** min(attempt - 1, 5))) + random.random()
                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass

    async def _heartbeat_loop(self, websocket: Any) -> None:
        while True:
            await asyncio.sleep(25)
            await self._send(websocket, {
                "type": "bot.heartbeat",
                "current_jobs": len(self._active),
                "available_slots": max(0, 1 - len(self._active)),
            })

    async def _handle_message(self, websocket: Any, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "execution.run":
            execution_id = str(message.get("execution_id") or message.get("job_id") or "")
            capability = message.get("capability")
            if not execution_id or capability not in self.capabilities:
                if execution_id:
                    await self._send_result(execution_id, {
                        "type": "execution.failed", "error": "Trabajo sin execution_id o capability válida"
                    })
                return
            if execution_id in self._active or execution_id in self._pending_results:
                continue_result = self._pending_results.get(execution_id)
                if continue_result:
                    await self._send_result(execution_id, continue_result)
                return
            self._active[execution_id] = None
            task = asyncio.create_task(self._execute(execution_id, message))
            self._active[execution_id] = task
            await self._send(websocket, {"type": "execution.started", "execution_id": execution_id})
        elif kind == "execution.ack":
            execution_id = str(message.get("execution_id") or "")
            self._pending_results.pop(execution_id, None)
            self._active.pop(execution_id, None)
            logger.info("Orchestrator acknowledged job %s (%s)", execution_id, message.get("job_status"))
            await self._send(websocket, {
                "type": "bot.heartbeat",
                "current_jobs": len(self._active),
                "available_slots": max(0, 1 - len(self._active)),
            })
        elif kind == "error":
            logger.error("Orchestrator error %s: %s", message.get("code"), message.get("message"))
        elif kind not in {"bot.heartbeat.ack", "bot.registered"}:
            logger.warning("Ignoring unsupported orchestrator message type %r", kind)

    async def _execute(self, execution_id: str, message: dict[str, Any]) -> None:
        try:
            payload = await asyncio.to_thread(self._load_input, message)
            request_body = {
                "id": str(message.get("job_id") or execution_id),
                "job_id": execution_id,
                "execution_id": execution_id,
                "capability": message["capability"],
                "payload": payload,
            }
            result = await asyncio.to_thread(self._submit, request_body)
            report = {"type": "execution.succeeded", "payload": result}
        except Exception as exc:
            logger.exception("Post bot failed job %s", execution_id)
            report = {"type": "execution.failed", "error": str(exc)[:4000]}
        self._pending_results[execution_id] = report
        websocket = self._websocket
        if websocket is not None:
            try:
                await self._send_result(execution_id, report)
            except Exception:
                logger.warning("Could not send result for %s; it will be replayed after reconnect", execution_id)

    def _load_input(self, message: dict[str, Any]) -> dict[str, Any]:
        input_url = message.get("input_url")
        if input_url:
            parsed = urlparse(self.url)
            origin = f"{'https' if parsed.scheme == 'wss' else 'http'}://{parsed.netloc}"
            target = urljoin(origin, str(input_url))
            target_parts = urlparse(target)
            origin_parts = urlparse(origin)
            if (target_parts.scheme, target_parts.netloc) != (origin_parts.scheme, origin_parts.netloc):
                raise ValueError("El input_url del orquestador debe pertenecer al mismo origen del WebSocket")
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    response = requests.get(
                        target,
                        headers={"Authorization": f"Bearer {self.token}"},
                        timeout=(5, 45),
                    )
                    response.raise_for_status()
                    document = response.json()
                    if isinstance(document.get("payload"), dict):
                        return document["payload"]
                    raise ValueError("La respuesta input del orquestador no contiene payload")
                except (requests.RequestException, ValueError) as exc:
                    last_error = exc
                    if attempt < 2:
                        time.sleep(1.0 * (attempt + 1))
            logger.warning("Could not fetch authenticated job input; using inline payload: %s", last_error)
        payload = message.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("El trabajo del orquestador contiene un payload inválido")
        return payload

    def _submit(self, request_body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {os.getenv('ORCHESTRATOR_TOKEN', '').strip()}",
            "Idempotency-Key": str(request_body["execution_id"]),
        }
        deadline = time.monotonic() + 1800
        while True:
            try:
                response = requests.post(
                    self.callback_url,
                    json=request_body,
                    headers=headers,
                    timeout=(5, 900),
                )
            except (requests.Timeout, requests.ConnectionError):
                if time.monotonic() >= deadline:
                    raise
                # The app may have completed the request even if its response
                # was lost. The stable execution ID makes this replay safe.
                time.sleep(3)
                continue
            if response.status_code == 409 and "ya está en curso" in response.text.casefold():
                if time.monotonic() >= deadline:
                    raise RuntimeError("La ejecución local permaneció en curso durante demasiado tiempo")
                time.sleep(5)
                continue
            if not response.ok:
                raise RuntimeError(
                    f"La entrada REST del bot devolvió {response.status_code}: {response.text[:1000]}"
                )
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("La entrada REST del bot devolvió una respuesta inválida")
            return data

    async def _send_result(self, execution_id: str, result: dict[str, Any]) -> None:
        await self._send(self._websocket, {"execution_id": execution_id, **result})

    async def _send(self, websocket: Any, message: dict[str, Any]) -> None:
        if websocket is None:
            raise ConnectionError("WebSocket desconectado")
        async with self._send_lock:
            await websocket.send(json.dumps(message, ensure_ascii=False))
