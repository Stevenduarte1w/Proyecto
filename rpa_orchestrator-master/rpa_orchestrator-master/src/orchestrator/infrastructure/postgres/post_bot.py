from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.application.post_bot import (
    PostBotHeartbeatMessage,
    PostBotJobConflictError,
    PostBotJobCreateRequest,
    PostBotJobOwnershipError,
    PostBotJobResultMessage,
    PostBotJobStateError,
    PostBotRegisterMessage,
)
from orchestrator.domain.post_bot import (
    CANCELLED,
    DISPATCHED,
    POST_BOT_ACTIVE_STATES,
    POST_BOT_TERMINAL_STATES,
    QUEUED,
    RUNNING,
)
from orchestrator.infrastructure.postgres.models import (
    PostBotJobEventModel,
    PostBotJobModel,
    PostBotWorkerModel,
)


class SqlAlchemyPostBotRepository:
    """Persistencia del canal aislado.

    Solo toca las tablas `post_bot_*`; nunca `flows`, `flow_steps`, `executions`
    ni `execution_checkpoints`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------
    async def register_worker(
        self,
        message: PostBotRegisterMessage,
        session_id: UUID,
    ) -> dict[str, Any]:
        result = await self._session.execute(
            select(PostBotWorkerModel).where(PostBotWorkerModel.bot_key == message.bot_key)
        )
        worker = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if worker is None:
            worker = PostBotWorkerModel(
                id=uuid4(),
                bot_key=message.bot_key,
                name=message.name,
                bot_type=message.bot_type,
                version=message.version,
                capabilities=list(message.capabilities),
                metadata_json=message.metadata,
                enabled=True,
                online=True,
                session_id=session_id,
                max_concurrency=message.max_concurrency,
                available_slots=message.available_slots,
                current_jobs=0,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
            self._session.add(worker)
        else:
            if not worker.enabled:
                raise PermissionError("Post bot worker is disabled")
            worker.name = message.name
            worker.bot_type = message.bot_type
            worker.version = message.version
            worker.capabilities = list(message.capabilities)
            worker.metadata_json = message.metadata
            worker.online = True
            worker.session_id = session_id
            worker.max_concurrency = message.max_concurrency
            worker.available_slots = message.available_slots
            worker.last_seen_at = now
            worker.updated_at = now
        await self._session.commit()
        return _worker_dict(worker, online=True)

    async def heartbeat(
        self,
        worker_id: UUID,
        message: PostBotHeartbeatMessage,
    ) -> None:
        worker = await self._session.get(PostBotWorkerModel, worker_id)
        if worker is None or not worker.enabled:
            raise PermissionError("Post bot worker is not available")
        now = datetime.now(UTC)
        worker.current_jobs = message.current_jobs
        worker.available_slots = message.available_slots
        worker.online = True
        worker.last_seen_at = now
        worker.updated_at = now
        await self._session.commit()

    async def mark_worker_offline(self, worker_id: UUID, session_id: UUID) -> None:
        worker = await self._session.get(PostBotWorkerModel, worker_id)
        if worker is None or worker.session_id != session_id:
            return
        worker.online = False
        worker.available_slots = 0
        worker.updated_at = datetime.now(UTC)
        await self._session.commit()

    async def get_worker_by_key(self, bot_key: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(PostBotWorkerModel).where(PostBotWorkerModel.bot_key == bot_key)
        )
        worker = result.scalar_one_or_none()
        return None if worker is None else _worker_dict(worker, online=worker.online)

    async def requeue_orphan_jobs(
        self,
        worker_id: UUID,
        keep_job_ids: set[UUID],
    ) -> list[UUID]:
        """Devuelve a la cola los trabajos que el worker ya no reporta como activos."""
        result = await self._session.execute(
            select(PostBotJobModel).where(
                PostBotJobModel.worker_id == worker_id,
                PostBotJobModel.status.in_(tuple(POST_BOT_ACTIVE_STATES)),
            )
        )
        requeued: list[UUID] = []
        now = datetime.now(UTC)
        for job in result.scalars():
            if job.id in keep_job_ids:
                continue
            job.status = QUEUED
            job.worker_id = None
            job.dispatched_at = None
            job.started_at = None
            job.updated_at = now
            self._session.add(
                _event(job.id, worker_id, "requeued", {"reason": "worker_reconnected"})
            )
            requeued.append(job.id)
        if requeued:
            await self._session.commit()
        return requeued

    # ------------------------------------------------------------------
    # Trabajos
    # ------------------------------------------------------------------
    async def enqueue_job(
        self,
        request: PostBotJobCreateRequest,
    ) -> tuple[dict[str, Any], bool]:
        payload_hash = _payload_hash(request.capability, request.payload)
        if request.external_ref:
            existing = await self._session.execute(
                select(PostBotJobModel).where(
                    PostBotJobModel.external_ref == request.external_ref
                )
            )
            duplicate = existing.scalar_one_or_none()
            if duplicate is not None:
                if duplicate.payload_hash != payload_hash:
                    raise PostBotJobConflictError(
                        f"external_ref {request.external_ref!r} already exists "
                        "with a different payload"
                    )
                return _job_dict(duplicate), True

        now = datetime.now(UTC)
        job = PostBotJobModel(
            id=uuid4(),
            capability=request.capability,
            status=QUEUED,
            priority=request.priority,
            payload=request.payload,
            payload_hash=payload_hash,
            external_ref=request.external_ref,
            requested_by=request.requested_by,
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(job)
        self._session.add(
            _event(job.id, None, "queued", {"requested_by": request.requested_by})
        )
        await self._session.commit()
        return _job_dict(job), False

    async def claim_jobs(
        self,
        worker_id: UUID,
        capabilities: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Reclama trabajos en exclusiva con `FOR UPDATE SKIP LOCKED`."""
        if limit <= 0 or not capabilities:
            return []
        candidates = await self._session.execute(
            select(PostBotJobModel)
            .where(
                PostBotJobModel.status == QUEUED,
                PostBotJobModel.capability.in_(tuple(capabilities)),
            )
            .order_by(
                PostBotJobModel.priority.desc(),
                PostBotJobModel.created_at.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        now = datetime.now(UTC)
        claimed: list[dict[str, Any]] = []
        for job in candidates.scalars():
            job.status = DISPATCHED
            job.worker_id = worker_id
            job.attempts += 1
            job.dispatched_at = now
            job.updated_at = now
            self._session.add(
                _event(job.id, worker_id, "dispatched", {"attempt": job.attempts})
            )
            claimed.append(_job_dict(job))
        if claimed:
            await self._session.commit()
        return claimed

    async def release_job(self, job_id: UUID, reason: str) -> None:
        job = await self._session.get(PostBotJobModel, job_id)
        if job is None or job.status in POST_BOT_TERMINAL_STATES:
            return
        worker_id = job.worker_id
        job.status = QUEUED
        job.worker_id = None
        job.dispatched_at = None
        job.updated_at = datetime.now(UTC)
        self._session.add(_event(job_id, worker_id, "requeued", {"reason": reason}))
        await self._session.commit()

    async def mark_running(self, job_id: UUID, worker_id: UUID) -> dict[str, Any]:
        job = await self._require_owned_job(job_id, worker_id)
        if job.status in POST_BOT_TERMINAL_STATES:
            raise PostBotJobStateError(f"Job is already {job.status}")
        now = datetime.now(UTC)
        job.status = RUNNING
        job.started_at = job.started_at or now
        job.updated_at = now
        self._session.add(_event(job_id, worker_id, "started", {}))
        await self._session.commit()
        return _job_dict(job)

    async def complete_job(
        self,
        job_id: UUID,
        worker_id: UUID,
        message: PostBotJobResultMessage,
    ) -> tuple[dict[str, Any], bool]:
        job = await self._require_owned_job(job_id, worker_id)
        if job.status in POST_BOT_TERMINAL_STATES:
            return _job_dict(job), True

        now = datetime.now(UTC)
        job.status = message.status
        job.result = message.payload
        job.error = message.failure_reason
        job.started_at = job.started_at or job.dispatched_at or now
        job.finished_at = now
        job.updated_at = now
        self._session.add(
            _event(
                job_id,
                worker_id,
                message.status,
                {"error": message.failure_reason} if message.failure_reason else {},
            )
        )
        await self._session.commit()
        return _job_dict(job), False

    async def cancel_job(self, job_id: UUID) -> dict[str, Any]:
        job = await self._session.get(PostBotJobModel, job_id)
        if job is None:
            raise LookupError("Post bot job not found")
        if job.status in POST_BOT_TERMINAL_STATES:
            raise PostBotJobStateError(f"Job is already {job.status}")
        if job.status != QUEUED:
            raise PostBotJobStateError(
                "Only queued jobs can be cancelled; the worker is already running this one"
            )
        now = datetime.now(UTC)
        job.status = CANCELLED
        job.finished_at = now
        job.updated_at = now
        self._session.add(_event(job_id, job.worker_id, CANCELLED, {}))
        await self._session.commit()
        return _job_dict(job)

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    async def get_job(self, job_id: UUID) -> dict[str, Any] | None:
        job = await self._session.get(PostBotJobModel, job_id)
        return None if job is None else _job_dict(job)

    async def list_jobs(
        self,
        status: str | None,
        capability: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        statement = select(PostBotJobModel)
        if status:
            statement = statement.where(PostBotJobModel.status == status)
        if capability:
            statement = statement.where(PostBotJobModel.capability == capability)
        statement = statement.order_by(PostBotJobModel.created_at.desc()).limit(limit)
        result = await self._session.execute(statement)
        return [_job_dict(job) for job in result.scalars()]

    async def list_workers(self, presence_ttl_seconds: int) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(PostBotWorkerModel).order_by(PostBotWorkerModel.bot_key)
        )
        deadline = datetime.now(UTC) - timedelta(seconds=presence_ttl_seconds)
        return [
            _worker_dict(worker, online=_is_online(worker, deadline))
            for worker in result.scalars()
        ]

    async def overview(self, presence_ttl_seconds: int) -> dict[str, Any]:
        counts = await self._session.execute(
            select(PostBotJobModel.status, func.count()).group_by(PostBotJobModel.status)
        )
        by_status = {status: int(total) for status, total in counts.all()}
        workers = await self.list_workers(presence_ttl_seconds)
        return {
            "jobs": by_status,
            "queued": by_status.get(QUEUED, 0),
            "in_flight": sum(by_status.get(state, 0) for state in POST_BOT_ACTIVE_STATES),
            "workers": workers,
            "workers_online": sum(1 for worker in workers if worker["online"]),
            "presence_ttl_seconds": presence_ttl_seconds,
        }

    async def _require_owned_job(self, job_id: UUID, worker_id: UUID) -> PostBotJobModel:
        job = await self._session.get(PostBotJobModel, job_id)
        if job is None:
            raise LookupError("Post bot job not found")
        if job.worker_id is not None and job.worker_id != worker_id:
            raise PostBotJobOwnershipError("Job is assigned to a different worker")
        return job


def _is_online(worker: PostBotWorkerModel, deadline: datetime) -> bool:
    if not worker.online or worker.last_seen_at is None:
        return False
    last_seen = worker.last_seen_at
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    return last_seen >= deadline


def _worker_dict(worker: PostBotWorkerModel, *, online: bool) -> dict[str, Any]:
    return {
        "id": worker.id,
        "bot_key": worker.bot_key,
        "name": worker.name,
        "bot_type": worker.bot_type,
        "version": worker.version,
        "capabilities": list(worker.capabilities or []),
        "metadata": dict(worker.metadata_json or {}),
        "enabled": worker.enabled,
        "online": online,
        "max_concurrency": worker.max_concurrency,
        "available_slots": worker.available_slots,
        "current_jobs": worker.current_jobs,
        "last_seen_at": worker.last_seen_at,
    }


def _job_dict(job: PostBotJobModel) -> dict[str, Any]:
    return {
        "id": job.id,
        "capability": job.capability,
        "status": job.status,
        "priority": job.priority,
        "payload": dict(job.payload or {}),
        "external_ref": job.external_ref,
        "requested_by": job.requested_by,
        "worker_id": job.worker_id,
        "attempts": job.attempts,
        "result": job.result,
        "error": job.error,
        "dispatched_at": job.dispatched_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _event(
    job_id: UUID,
    worker_id: UUID | None,
    event_type: str,
    detail: dict[str, Any],
) -> PostBotJobEventModel:
    return PostBotJobEventModel(
        id=uuid4(),
        job_id=job_id,
        worker_id=worker_id,
        event_type=event_type,
        detail=detail,
        created_at=datetime.now(UTC),
    )


def _payload_hash(capability: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"capability": capability, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
