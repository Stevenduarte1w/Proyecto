"""Canal aislado del bot de posts.

Este módulo despacha trabajo al bot de posts y recibe sus resultados **sin
participar del motor de workflows SEO**. No importa ni invoca `AdvanceWorkflow`,
`DispatchExecution`, `SubmitExecutionResult` ni `ProcessExecutionCheckpoint`, y
no escribe en `flows`, `flow_steps`, `executions` ni `execution_checkpoints`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator

from orchestrator.domain.post_bot import POST_BOT_CAPABILITIES

logger = structlog.get_logger(__name__)

JobStatus = Literal["queued", "dispatched", "running", "succeeded", "failed", "cancelled"]


class PostBotMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PostBotRegisterMessage(PostBotMessage):
    """Primer mensaje del bot.

    Se acepta el mismo `bot.register` que ya emite `WebSocketBotClient`, para que
    el cliente del bot no tenga que reescribirse.
    """

    type: Literal["bot.register"] = "bot.register"
    bot_key: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=120)
    bot_type: str = Field(default="create_post", min_length=2, max_length=80)
    capabilities: list[str] = Field(min_length=1)
    version: str | None = Field(default=None, max_length=80)
    max_concurrency: int = Field(default=1, ge=1, le=100)
    available_slots: int = Field(default=1, ge=0, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    active_jobs: list[UUID] = Field(default_factory=list)
    active_executions: list[UUID] = Field(default_factory=list)

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_supported(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - POST_BOT_CAPABILITIES)
        if unknown:
            supported = ", ".join(sorted(POST_BOT_CAPABILITIES))
            raise ValueError(
                f"Unsupported capabilities: {', '.join(unknown)}. Supported: {supported}"
            )
        return value

    def claimed_jobs(self) -> set[UUID]:
        """Trabajos que el bot dice seguir procesando tras una reconexión."""
        return set(self.active_jobs) | set(self.active_executions)


class PostBotHeartbeatMessage(PostBotMessage):
    type: Literal["bot.heartbeat"] = "bot.heartbeat"
    current_jobs: int = Field(default=0, ge=0, le=10_000)
    available_slots: int = Field(default=0, ge=0, le=100)


class PostBotJobStartedMessage(PostBotMessage):
    type: Literal["execution.started"] = "execution.started"
    execution_id: UUID


class PostBotJobResultMessage(PostBotMessage):
    type: Literal["execution.succeeded", "execution.failed"]
    execution_id: UUID
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = Field(default=None, max_length=8_000)

    @property
    def succeeded(self) -> bool:
        return self.type == "execution.succeeded"

    @property
    def status(self) -> JobStatus:
        return "succeeded" if self.succeeded else "failed"

    @property
    def failure_reason(self) -> str | None:
        if self.succeeded:
            return None
        return self.error or "El bot reportó execution.failed sin detalle"


class PostBotJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: str = Field(default="posts.create")
    payload: dict[str, Any]
    priority: int = Field(default=0, ge=-100, le=100)
    external_ref: str | None = Field(default=None, max_length=240)
    requested_by: str | None = Field(default=None, max_length=120)

    @field_validator("capability")
    @classmethod
    def capability_is_supported(cls, value: str) -> str:
        if value not in POST_BOT_CAPABILITIES:
            supported = ", ".join(sorted(POST_BOT_CAPABILITIES))
            raise ValueError(f"Unsupported capability: {value}. Supported: {supported}")
        return value

    @field_validator("payload")
    @classmethod
    def payload_is_not_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("payload must not be empty")
        return value


class PostBotJobReceipt(BaseModel):
    job_id: UUID
    status: JobStatus
    duplicate: bool = False


class PostBotJobConflictError(RuntimeError):
    """El mismo `external_ref` ya existe con un payload distinto."""


class PostBotJobOwnershipError(RuntimeError):
    """El trabajo pertenece a otro worker."""


class PostBotJobStateError(RuntimeError):
    """El trabajo no admite la transición pedida."""


class PostBotRepository(Protocol):
    async def register_worker(
        self,
        message: PostBotRegisterMessage,
        session_id: UUID,
    ) -> dict[str, Any]: ...

    async def heartbeat(
        self,
        worker_id: UUID,
        message: PostBotHeartbeatMessage,
    ) -> None: ...

    async def mark_worker_offline(self, worker_id: UUID, session_id: UUID) -> None: ...

    async def get_worker_by_key(self, bot_key: str) -> dict[str, Any] | None: ...

    async def requeue_orphan_jobs(
        self,
        worker_id: UUID,
        keep_job_ids: set[UUID],
    ) -> list[UUID]: ...

    async def enqueue_job(
        self,
        request: PostBotJobCreateRequest,
    ) -> tuple[dict[str, Any], bool]: ...

    async def claim_jobs(
        self,
        worker_id: UUID,
        capabilities: list[str],
        limit: int,
    ) -> list[dict[str, Any]]: ...

    async def release_job(self, job_id: UUID, reason: str) -> None: ...

    async def mark_running(self, job_id: UUID, worker_id: UUID) -> dict[str, Any]: ...

    async def complete_job(
        self,
        job_id: UUID,
        worker_id: UUID,
        message: PostBotJobResultMessage,
    ) -> tuple[dict[str, Any], bool]: ...

    async def cancel_job(self, job_id: UUID) -> dict[str, Any]: ...

    async def get_job(self, job_id: UUID) -> dict[str, Any] | None: ...

    async def list_jobs(
        self,
        status: str | None,
        capability: str | None,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    async def list_workers(self, presence_ttl_seconds: int) -> list[dict[str, Any]]: ...

    async def overview(self, presence_ttl_seconds: int) -> dict[str, Any]: ...


class PostBotCommandGateway(Protocol):
    def is_connected(self, worker_id: UUID) -> bool: ...

    def connected_worker_ids(self) -> list[UUID]: ...

    def capabilities_of(self, worker_id: UUID) -> list[str]: ...

    async def send_job(self, worker_id: UUID, job: dict[str, Any]) -> None: ...


class PostBotService:
    """Casos de uso del canal aislado del bot de posts."""

    def __init__(
        self,
        repository: PostBotRepository,
        command_gateway: PostBotCommandGateway,
        presence_ttl_seconds: int,
    ) -> None:
        self._repository = repository
        self._gateway = command_gateway
        self._presence_ttl_seconds = presence_ttl_seconds

    # ------------------------------------------------------------------
    # Conexión del worker
    # ------------------------------------------------------------------
    async def register(
        self,
        message: PostBotRegisterMessage,
        session_id: UUID,
    ) -> tuple[dict[str, Any], list[UUID]]:
        worker = await self._repository.register_worker(message, session_id)
        requeued = await self._repository.requeue_orphan_jobs(
            UUID(str(worker["id"])),
            message.claimed_jobs(),
        )
        return worker, requeued

    async def heartbeat(
        self,
        worker_id: UUID,
        message: PostBotHeartbeatMessage,
    ) -> None:
        await self._repository.heartbeat(worker_id, message)

    async def disconnect(self, worker_id: UUID, session_id: UUID) -> None:
        await self._repository.mark_worker_offline(worker_id, session_id)

    async def get_worker_by_key(self, bot_key: str) -> dict[str, Any] | None:
        return await self._repository.get_worker_by_key(bot_key)

    # ------------------------------------------------------------------
    # Ciclo de vida de un trabajo
    # ------------------------------------------------------------------
    async def enqueue(self, request: PostBotJobCreateRequest) -> tuple[dict[str, Any], bool]:
        job, duplicate = await self._repository.enqueue_job(request)
        if not duplicate:
            await self.dispatch_pending()
        return job, duplicate

    async def dispatch_pending(self, worker_id: UUID | None = None, limit: int = 0) -> list[UUID]:
        """Entrega trabajos encolados a los workers conectados con cupo libre."""
        worker_ids = (
            [worker_id] if worker_id is not None else self._gateway.connected_worker_ids()
        )
        dispatched: list[UUID] = []
        for candidate in worker_ids:
            if not self._gateway.is_connected(candidate):
                continue
            capabilities = self._gateway.capabilities_of(candidate)
            if not capabilities:
                continue
            slots = limit if limit > 0 else await self._available_slots(candidate)
            if slots <= 0:
                continue
            jobs = await self._repository.claim_jobs(candidate, capabilities, slots)
            for job in jobs:
                job_id = UUID(str(job["id"]))
                try:
                    await self._gateway.send_job(candidate, job)
                except Exception as exc:  # noqa: BLE001 - se devuelve a la cola
                    await self._repository.release_job(job_id, f"dispatch_failed: {exc}")
                    logger.warning(
                        "post_bot_job_dispatch_failed",
                        job_id=str(job_id),
                        worker_id=str(candidate),
                        error=str(exc),
                    )
                    continue
                dispatched.append(job_id)
        return dispatched

    async def mark_running(self, job_id: UUID, worker_id: UUID) -> dict[str, Any]:
        return await self._repository.mark_running(job_id, worker_id)

    async def complete(
        self,
        worker_id: UUID,
        message: PostBotJobResultMessage,
    ) -> tuple[dict[str, Any], bool]:
        job, duplicate = await self._repository.complete_job(
            message.execution_id,
            worker_id,
            message,
        )
        if not duplicate:
            await self.dispatch_pending(worker_id=worker_id)
        return job, duplicate

    async def cancel(self, job_id: UUID) -> dict[str, Any]:
        return await self._repository.cancel_job(job_id)

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    async def get_job(self, job_id: UUID) -> dict[str, Any] | None:
        return await self._repository.get_job(job_id)

    async def list_jobs(
        self,
        status: str | None,
        capability: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        return await self._repository.list_jobs(status, capability, limit)

    async def list_workers(self) -> list[dict[str, Any]]:
        return await self._repository.list_workers(self._presence_ttl_seconds)

    async def overview(self) -> dict[str, Any]:
        return await self._repository.overview(self._presence_ttl_seconds)

    async def _available_slots(self, worker_id: UUID) -> int:
        workers = await self._repository.list_workers(self._presence_ttl_seconds)
        for worker in workers:
            if UUID(str(worker["id"])) == worker_id:
                return max(0, int(worker.get("available_slots") or 0))
        return 0


def job_input_document(job: dict[str, Any]) -> dict[str, Any]:
    """Documento que el bot descarga desde `input_url`."""
    return {
        "execution_id": str(job["id"]),
        "job_id": str(job["id"]),
        "capability": job["capability"],
        "created_at": _isoformat(job.get("created_at")),
        "payload": job.get("payload") or {},
    }


def _isoformat(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None if value is None else str(value)
