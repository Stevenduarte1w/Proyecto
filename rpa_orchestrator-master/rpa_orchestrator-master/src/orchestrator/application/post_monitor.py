from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PostMonitorMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PostMonitorRegisterMessage(PostMonitorMessage):
    type: Literal["post_monitor.register"] = "post_monitor.register"
    schema_version: Literal["post-monitor.register.v1"] = "post-monitor.register.v1"
    bot_key: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=120)
    version: str | None = Field(default=None, max_length=80)
    environment: str = Field(default="production", min_length=2, max_length=40)
    started_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PostMonitorHeartbeatMessage(PostMonitorMessage):
    type: Literal["post_monitor.heartbeat"] = "post_monitor.heartbeat"
    schema_version: Literal["post-monitor.heartbeat.v1"] = "post-monitor.heartbeat.v1"
    sent_at: datetime | None = None
    status: Literal["idle", "running", "degraded"] = "idle"
    current_jobs: int = Field(default=0, ge=0, le=10_000)
    outbox_pending: int = Field(default=0, ge=0, le=1_000_000)


class PostMonitorTarget(PostMonitorMessage):
    external_id: str | None = Field(default=None, max_length=240)
    url: str | None = Field(default=None, max_length=2_000)
    title: str | None = Field(default=None, max_length=500)


class PostMonitorArtifact(PostMonitorMessage):
    name: str = Field(min_length=1, max_length=240)
    url: str = Field(min_length=1, max_length=2_000)
    content_type: str | None = Field(default=None, max_length=120)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)


class PostMonitorRunError(PostMonitorMessage):
    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=4_000)
    retryable: bool = False


class PostMonitorRunPayload(PostMonitorMessage):
    run_id: UUID
    status: Literal["succeeded", "failed", "partial", "cancelled"]
    started_at: datetime
    finished_at: datetime
    duration_ms: int | None = Field(default=None, ge=0)
    target: PostMonitorTarget = Field(default_factory=PostMonitorTarget)
    summary: str | None = Field(default=None, max_length=4_000)
    metrics: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error: PostMonitorRunError | None = None
    artifacts: list[PostMonitorArtifact] = Field(default_factory=list, max_length=100)

    @field_validator("started_at")
    @classmethod
    def started_at_has_timezone(cls, value: datetime) -> datetime:
        return _require_timezone(value)

    @field_validator("finished_at")
    @classmethod
    def finished_at_is_not_before_start(
        cls,
        value: datetime,
        info: Any,
    ) -> datetime:
        value = _require_timezone(value)
        started_at = info.data.get("started_at")
        if isinstance(started_at, datetime) and value < started_at:
            raise ValueError("finished_at must not be before started_at")
        return value


class PostMonitorRunResultMessage(PostMonitorMessage):
    type: Literal["post_monitor.run.result"] = "post_monitor.run.result"
    schema_version: Literal["post-monitor.result.v1"] = "post-monitor.result.v1"
    event_id: UUID
    bot_key: str = Field(min_length=2, max_length=120)
    occurred_at: datetime
    payload: PostMonitorRunPayload

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_has_timezone(cls, value: datetime) -> datetime:
        return _require_timezone(value)


class PostMonitorAlertRule(PostMonitorMessage):
    rule_id: str = Field(min_length=1, max_length=160)
    config_version: str | None = Field(default=None, max_length=120)
    configured_by: str = Field(default="post-bot", min_length=1, max_length=120)


class PostMonitorAlertPayload(PostMonitorMessage):
    alert_id: UUID
    run_id: UUID | None = None
    severity: Literal["info", "warning", "critical"] = "warning"
    metric: str = Field(min_length=1, max_length=160)
    observed_value: float
    operator: Literal["lt", "lte", "gt", "gte", "eq"] = "lt"
    threshold: float
    unit: str | None = Field(default=None, max_length=80)
    message: str = Field(min_length=1, max_length=4_000)
    rule: PostMonitorAlertRule
    target: PostMonitorTarget = Field(default_factory=PostMonitorTarget)
    details: dict[str, Any] = Field(default_factory=dict)


class PostMonitorThresholdAlertMessage(PostMonitorMessage):
    type: Literal["post_monitor.threshold.alert"] = "post_monitor.threshold.alert"
    schema_version: Literal["post-monitor.alert.v1"] = "post-monitor.alert.v1"
    event_id: UUID
    bot_key: str = Field(min_length=2, max_length=120)
    occurred_at: datetime
    payload: PostMonitorAlertPayload

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_has_timezone(cls, value: datetime) -> datetime:
        return _require_timezone(value)


class PostMonitorAlertUpdateRequest(PostMonitorMessage):
    status: Literal["acknowledged", "resolved", "dismissed"]


class PostMonitorEventReceipt(BaseModel):
    event_id: UUID
    stored_at: datetime
    duplicate: bool = False


class PostMonitorEventConflictError(RuntimeError):
    pass


class PostMonitorProjectionConflictError(RuntimeError):
    pass


class PostMonitorRepository(Protocol):
    async def register_bot(self, message: PostMonitorRegisterMessage) -> dict[str, Any]: ...

    async def heartbeat(
        self,
        bot_id: UUID,
        message: PostMonitorHeartbeatMessage,
    ) -> None: ...

    async def ingest_result(
        self,
        bot_id: UUID,
        message: PostMonitorRunResultMessage,
    ) -> PostMonitorEventReceipt: ...

    async def ingest_alert(
        self,
        bot_id: UUID,
        message: PostMonitorThresholdAlertMessage,
    ) -> PostMonitorEventReceipt: ...

    async def overview(self, presence_ttl_seconds: int) -> dict[str, Any]: ...

    async def list_runs(
        self,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    async def list_alerts(
        self,
        status: str | None,
        severity: str | None,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    async def update_alert(
        self,
        alert_id: UUID,
        status: str,
    ) -> dict[str, Any] | None: ...


class PostMonitorService:
    def __init__(
        self,
        repository: PostMonitorRepository,
        presence_ttl_seconds: int,
    ) -> None:
        self._repository = repository
        self._presence_ttl_seconds = presence_ttl_seconds

    async def register(self, message: PostMonitorRegisterMessage) -> dict[str, Any]:
        return await self._repository.register_bot(message)

    async def heartbeat(
        self,
        bot_id: UUID,
        message: PostMonitorHeartbeatMessage,
    ) -> None:
        await self._repository.heartbeat(bot_id, message)

    async def ingest_result(
        self,
        bot_id: UUID,
        registered_bot_key: str,
        message: PostMonitorRunResultMessage,
    ) -> PostMonitorEventReceipt:
        self._ensure_bot_key(registered_bot_key, message.bot_key)
        return await self._repository.ingest_result(bot_id, message)

    async def ingest_alert(
        self,
        bot_id: UUID,
        registered_bot_key: str,
        message: PostMonitorThresholdAlertMessage,
    ) -> PostMonitorEventReceipt:
        self._ensure_bot_key(registered_bot_key, message.bot_key)
        return await self._repository.ingest_alert(bot_id, message)

    async def overview(self) -> dict[str, Any]:
        return await self._repository.overview(self._presence_ttl_seconds)

    async def list_runs(
        self,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        return await self._repository.list_runs(status, limit)

    async def list_alerts(
        self,
        status: str | None,
        severity: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        return await self._repository.list_alerts(status, severity, limit)

    async def update_alert(
        self,
        alert_id: UUID,
        status: str,
    ) -> dict[str, Any] | None:
        return await self._repository.update_alert(alert_id, status)

    @staticmethod
    def _ensure_bot_key(registered_bot_key: str, reported_bot_key: str) -> None:
        if registered_bot_key != reported_bot_key:
            raise PermissionError("Event bot_key does not match the registered connection")


def _require_timezone(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    return value
