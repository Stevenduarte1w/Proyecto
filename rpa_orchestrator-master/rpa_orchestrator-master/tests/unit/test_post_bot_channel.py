from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from orchestrator.api.v1.dependencies import post_bot_service
from orchestrator.api.v1.routes.post_bot import router
from orchestrator.application.post_bot import (
    PostBotJobCreateRequest,
    PostBotJobResultMessage,
    PostBotRegisterMessage,
    PostBotService,
    job_input_document,
)
from orchestrator.core.config import Settings, get_settings


class FakePostBotRepository:
    def __init__(self) -> None:
        self.worker_id = uuid4()
        self.jobs: dict[UUID, dict[str, Any]] = {}
        self.heartbeats: list[Any] = []
        self.requeued: list[UUID] = []
        self.offline_calls: list[tuple[UUID, UUID]] = []

    async def register_worker(
        self,
        message: PostBotRegisterMessage,
        session_id: UUID,
    ) -> dict[str, Any]:
        return {
            "id": self.worker_id,
            "bot_key": message.bot_key,
            "name": message.name,
            "capabilities": list(message.capabilities),
            "enabled": True,
            "online": True,
            "available_slots": message.available_slots,
        }

    async def heartbeat(self, worker_id: UUID, message: Any) -> None:
        assert worker_id == self.worker_id
        self.heartbeats.append(message)

    async def mark_worker_offline(self, worker_id: UUID, session_id: UUID) -> None:
        self.offline_calls.append((worker_id, session_id))

    async def get_worker_by_key(self, bot_key: str) -> dict[str, Any] | None:
        return {"id": self.worker_id, "bot_key": bot_key}

    async def requeue_orphan_jobs(
        self,
        worker_id: UUID,
        keep_job_ids: set[UUID],
    ) -> list[UUID]:
        requeued = [
            job_id
            for job_id, job in self.jobs.items()
            if job["status"] == "dispatched" and job_id not in keep_job_ids
        ]
        for job_id in requeued:
            self.jobs[job_id]["status"] = "queued"
            self.jobs[job_id]["worker_id"] = None
        self.requeued.extend(requeued)
        return requeued

    async def enqueue_job(
        self,
        request: PostBotJobCreateRequest,
    ) -> tuple[dict[str, Any], bool]:
        for job in self.jobs.values():
            if request.external_ref and job["external_ref"] == request.external_ref:
                return job, True
        job_id = uuid4()
        job = {
            "id": job_id,
            "capability": request.capability,
            "status": "queued",
            "priority": request.priority,
            "payload": request.payload,
            "external_ref": request.external_ref,
            "requested_by": request.requested_by,
            "worker_id": None,
            "attempts": 0,
            "result": None,
            "error": None,
            "created_at": None,
        }
        self.jobs[job_id] = job
        return job, False

    async def claim_jobs(
        self,
        worker_id: UUID,
        capabilities: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        claimed: list[dict[str, Any]] = []
        for job in self.jobs.values():
            if len(claimed) >= limit:
                break
            if job["status"] == "queued" and job["capability"] in capabilities:
                job["status"] = "dispatched"
                job["worker_id"] = worker_id
                job["attempts"] += 1
                claimed.append(job)
        return claimed

    async def release_job(self, job_id: UUID, reason: str) -> None:
        self.jobs[job_id]["status"] = "queued"
        self.jobs[job_id]["worker_id"] = None

    async def mark_running(self, job_id: UUID, worker_id: UUID) -> dict[str, Any]:
        job = self.jobs[job_id]
        job["status"] = "running"
        return job

    async def complete_job(
        self,
        job_id: UUID,
        worker_id: UUID,
        message: PostBotJobResultMessage,
    ) -> tuple[dict[str, Any], bool]:
        job = self.jobs.get(job_id)
        if job is None:
            raise LookupError("not found")
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return job, True
        job["status"] = message.status
        job["result"] = message.payload
        job["error"] = message.failure_reason
        return job, False

    async def cancel_job(self, job_id: UUID) -> dict[str, Any]:
        job = self.jobs[job_id]
        job["status"] = "cancelled"
        return job

    async def get_job(self, job_id: UUID) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    async def list_jobs(
        self,
        status: str | None,
        capability: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        return [
            job
            for job in self.jobs.values()
            if (status is None or job["status"] == status)
            and (capability is None or job["capability"] == capability)
        ][:limit]

    async def list_workers(self, presence_ttl_seconds: int) -> list[dict[str, Any]]:
        return [{"id": self.worker_id, "online": True, "available_slots": 5}]

    async def overview(self, presence_ttl_seconds: int) -> dict[str, Any]:
        return {"jobs": {}, "queued": 0, "in_flight": 0, "workers": []}


class FakeGateway:
    def __init__(self, worker_id: UUID, capabilities: list[str]) -> None:
        self.worker_id = worker_id
        self.capabilities = capabilities
        self.sent: list[dict[str, Any]] = []
        self.fail_next = False

    def is_connected(self, worker_id: UUID) -> bool:
        return worker_id == self.worker_id

    def connected_worker_ids(self) -> list[UUID]:
        return [self.worker_id]

    def capabilities_of(self, worker_id: UUID) -> list[str]:
        return self.capabilities

    async def send_job(self, worker_id: UUID, job: dict[str, Any]) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("socket closed")
        self.sent.append(job)


def _service(
    repository: FakePostBotRepository,
    gateway: FakeGateway,
) -> PostBotService:
    return PostBotService(
        repository=repository,
        command_gateway=gateway,
        presence_ttl_seconds=60,
    )


def _register_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "type": "bot.register",
        "bot_key": "post-bot-v3",
        "name": "Post Bot v3",
        "bot_type": "create_post",
        "capabilities": ["posts.create", "posts.optimize"],
        "version": "3.0.0",
        "max_concurrency": 2,
        "available_slots": 2,
        "metadata": {"runtime": "python"},
    }
    payload.update(overrides)
    return payload


TOKEN = "post-bot-secret"  # noqa: S105 - credencial de prueba
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _app(service: PostBotService) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/post-bot")
    app.dependency_overrides[post_bot_service] = lambda: service
    return app


@pytest.fixture(autouse=True)
def _bot_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """El canal autentica contra BOT_TOKENS, igual que /api/v1/bots/ws."""
    settings = Settings(bot_tokens={TOKEN: "post-bot-v3"})
    monkeypatch.setattr(
        "orchestrator.api.v1.routes.post_bot.get_settings",
        lambda: settings,
    )
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Contrato de mensajes
# ---------------------------------------------------------------------------
def test_register_rejects_capabilities_outside_the_post_bot() -> None:
    with pytest.raises(ValidationError):
        PostBotRegisterMessage.model_validate(
            _register_payload(capabilities=["posts.create", "backlinks.saaf"])
        )


def test_register_accepts_the_existing_bot_client_message() -> None:
    message = PostBotRegisterMessage.model_validate(_register_payload())

    assert message.bot_key == "post-bot-v3"
    assert message.claimed_jobs() == set()


def test_failed_result_keeps_a_reason_even_without_error_text() -> None:
    message = PostBotJobResultMessage.model_validate(
        {"type": "execution.failed", "execution_id": str(uuid4())}
    )

    assert message.status == "failed"
    assert message.failure_reason is not None


def test_job_create_request_rejects_unknown_capability() -> None:
    with pytest.raises(ValidationError):
        PostBotJobCreateRequest.model_validate(
            {"capability": "posts.destroy", "payload": {"post_title": "x"}}
        )


def test_job_input_document_matches_the_bot_contract() -> None:
    job_id = uuid4()
    document = job_input_document(
        {
            "id": job_id,
            "capability": "posts.create",
            "payload": {"post_title": "Hola"},
            "created_at": None,
        }
    )

    assert document["execution_id"] == str(job_id)
    assert document["payload"] == {"post_title": "Hola"}


# ---------------------------------------------------------------------------
# Reparto
# ---------------------------------------------------------------------------
async def test_enqueue_dispatches_to_a_connected_worker() -> None:
    repository = FakePostBotRepository()
    gateway = FakeGateway(repository.worker_id, ["posts.create"])
    service = _service(repository, gateway)

    job, duplicate = await service.enqueue(
        PostBotJobCreateRequest(payload={"post_title": "Hola"})
    )

    assert duplicate is False
    assert len(gateway.sent) == 1
    assert repository.jobs[UUID(str(job["id"]))]["status"] == "dispatched"


async def test_job_returns_to_the_queue_when_the_socket_fails() -> None:
    repository = FakePostBotRepository()
    gateway = FakeGateway(repository.worker_id, ["posts.create"])
    gateway.fail_next = True
    service = _service(repository, gateway)

    job, _ = await service.enqueue(PostBotJobCreateRequest(payload={"post_title": "Hola"}))

    assert gateway.sent == []
    assert repository.jobs[UUID(str(job["id"]))]["status"] == "queued"


async def test_worker_only_receives_its_declared_capabilities() -> None:
    repository = FakePostBotRepository()
    gateway = FakeGateway(repository.worker_id, ["posts.create"])
    service = _service(repository, gateway)

    await service.enqueue(
        PostBotJobCreateRequest(capability="posts.optimize", payload={"target": "https://x/y"})
    )

    assert gateway.sent == []


async def test_reconnect_requeues_jobs_the_worker_no_longer_reports() -> None:
    repository = FakePostBotRepository()
    gateway = FakeGateway(repository.worker_id, ["posts.create"])
    service = _service(repository, gateway)
    job, _ = await service.enqueue(PostBotJobCreateRequest(payload={"post_title": "Hola"}))

    _, requeued = await service.register(
        PostBotRegisterMessage.model_validate(_register_payload()),
        uuid4(),
    )

    assert requeued == [UUID(str(job["id"]))]


async def test_reconnect_keeps_jobs_the_worker_still_reports() -> None:
    repository = FakePostBotRepository()
    gateway = FakeGateway(repository.worker_id, ["posts.create"])
    service = _service(repository, gateway)
    job, _ = await service.enqueue(PostBotJobCreateRequest(payload={"post_title": "Hola"}))

    _, requeued = await service.register(
        PostBotRegisterMessage.model_validate(
            _register_payload(active_jobs=[str(job["id"])])
        ),
        uuid4(),
    )

    assert requeued == []


async def test_repeated_terminal_event_is_acknowledged_without_overwriting() -> None:
    repository = FakePostBotRepository()
    gateway = FakeGateway(repository.worker_id, ["posts.create"])
    service = _service(repository, gateway)
    job, _ = await service.enqueue(PostBotJobCreateRequest(payload={"post_title": "Hola"}))
    message = PostBotJobResultMessage.model_validate(
        {
            "type": "execution.succeeded",
            "execution_id": str(job["id"]),
            "payload": {"posts": [{"url": "https://example.com/a"}]},
        }
    )
    await service.complete(repository.worker_id, message)

    _, duplicate = await service.complete(repository.worker_id, message)

    assert duplicate is True
    assert repository.jobs[UUID(str(job["id"]))]["result"] == {
        "posts": [{"url": "https://example.com/a"}]
    }


# ---------------------------------------------------------------------------
# WebSocket de punta a punta
# ---------------------------------------------------------------------------
def test_websocket_completes_a_job_round_trip() -> None:
    repository = FakePostBotRepository()
    gateway = FakeGateway(repository.worker_id, ["posts.create"])
    service = _service(repository, gateway)

    with TestClient(_app(service)) as client:
        with client.websocket_connect("/api/v1/post-bot/ws", headers=AUTH) as websocket:
            websocket.send_json(_register_payload())
            registered = websocket.receive_json()
            assert registered["type"] == "bot.registered"

            websocket.send_json({"type": "bot.heartbeat", "current_jobs": 0, "available_slots": 2})
            assert websocket.receive_json()["type"] == "bot.heartbeat.ack"


def test_websocket_rejects_workflow_messages() -> None:
    repository = FakePostBotRepository()
    gateway = FakeGateway(repository.worker_id, ["posts.create"])
    service = _service(repository, gateway)

    with TestClient(_app(service)) as client:
        with client.websocket_connect("/api/v1/post-bot/ws", headers=AUTH) as websocket:
            websocket.send_json(_register_payload())
            websocket.receive_json()

            websocket.send_json({"type": "execution.checkpoint", "execution_id": str(uuid4())})
            error = websocket.receive_json()

    assert error["code"] == "unsupported_message_type"


def test_websocket_requires_bot_register_first() -> None:
    repository = FakePostBotRepository()
    gateway = FakeGateway(repository.worker_id, ["posts.create"])
    service = _service(repository, gateway)

    with TestClient(_app(service)) as client:
        with client.websocket_connect("/api/v1/post-bot/ws", headers=AUTH) as websocket:
            websocket.send_json({"type": "bot.heartbeat", "available_slots": 1})
            error = websocket.receive_json()

    assert error["code"] == "invalid_first_message"


def test_websocket_rejects_a_connection_without_credentials() -> None:
    repository = FakePostBotRepository()
    gateway = FakeGateway(repository.worker_id, ["posts.create"])
    service = _service(repository, gateway)

    with TestClient(_app(service)) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/v1/post-bot/ws") as websocket:
                websocket.receive_json()


def test_websocket_rejects_a_bot_key_that_does_not_match_the_token() -> None:
    repository = FakePostBotRepository()
    gateway = FakeGateway(repository.worker_id, ["posts.create"])
    service = _service(repository, gateway)

    with TestClient(_app(service)) as client:
        with client.websocket_connect("/api/v1/post-bot/ws", headers=AUTH) as websocket:
            websocket.send_json(_register_payload(bot_key="otro-bot"))
            error = websocket.receive_json()

    assert error["code"] == "forbidden"


def test_job_input_is_denied_for_a_job_of_another_worker() -> None:
    repository = FakePostBotRepository()
    gateway = FakeGateway(repository.worker_id, ["posts.create"])
    service = _service(repository, gateway)

    job_id = uuid4()
    repository.jobs[job_id] = {
        "id": job_id,
        "capability": "posts.create",
        "status": "dispatched",
        "payload": {"post_title": "Hola"},
        "external_ref": None,
        "worker_id": uuid4(),  # otro worker
        "created_at": None,
    }

    with TestClient(_app(service)) as client:
        response = client.get(f"/api/v1/post-bot/jobs/{job_id}/input", headers=AUTH)

    assert response.status_code == 403


def test_job_input_requires_credentials() -> None:
    repository = FakePostBotRepository()
    gateway = FakeGateway(repository.worker_id, ["posts.create"])
    service = _service(repository, gateway)

    with TestClient(_app(service)) as client:
        response = client.get(f"/api/v1/post-bot/jobs/{uuid4()}/input")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Aislamiento respecto al motor de workflows
# ---------------------------------------------------------------------------
def test_channel_never_imports_the_workflow_engine() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "orchestrator"
    forbidden = (
        "advance_workflow",
        "dispatch_execution",
        "execution_documents",
        "execution_checkpoint",
    )
    sources = (
        root / "application" / "post_bot.py",
        root / "api" / "v1" / "routes" / "post_bot.py",
        root / "infrastructure" / "postgres" / "post_bot.py",
        root / "infrastructure" / "bots" / "post_bot_ws_manager.py",
    )

    for source in sources:
        text = source.read_text(encoding="utf-8")
        import_lines = [line for line in text.splitlines() if line.startswith(("import ", "from "))]
        for line in import_lines:
            assert not any(name in line for name in forbidden), f"{source.name}: {line}"


def test_channel_never_touches_workflow_tables() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "orchestrator"
    forbidden_models = (
        "ExecutionModel",
        "FlowModel",
        "FlowStepModel",
        "ExecutionCheckpointModel",
    )
    source = (root / "infrastructure" / "postgres" / "post_bot.py").read_text(encoding="utf-8")

    for model in forbidden_models:
        assert model not in source
