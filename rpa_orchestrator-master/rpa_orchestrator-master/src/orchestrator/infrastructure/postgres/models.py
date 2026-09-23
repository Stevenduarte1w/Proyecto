from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from orchestrator.domain.entities import ExecutionStatus, FlowStatus, FlowStepStatus, SeoFlowStep


def enum_values(enum_class: type) -> list[str]:
    return [item.value for item in enum_class]


class Base(DeclarativeBase):
    pass


class BotModel(Base):
    __tablename__ = "bots"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    bot_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    bot_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    base_url: Mapped[str | None] = mapped_column(String(500))
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    version: Mapped[str | None] = mapped_column(String(80))
    max_concurrency: Mapped[int] = mapped_column(nullable=False, default=1)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FlowModel(Base):
    __tablename__ = "flows"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    flow_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    page_url: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    campaign: Mapped[str | None] = mapped_column(String(120))
    commercial_objective: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[FlowStatus] = mapped_column(
        Enum(FlowStatus, name="flow_status", values_callable=enum_values),
        nullable=False,
        index=True,
    )
    current_step: Mapped[SeoFlowStep] = mapped_column(
        Enum(SeoFlowStep, name="seo_flow_step", values_callable=enum_values),
        nullable=False,
        index=True,
    )
    initial_document_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FlowStepModel(Base):
    __tablename__ = "flow_steps"
    __table_args__ = (UniqueConstraint("flow_id", "step_name", name="uq_flow_steps_flow_step"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    flow_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("flows.id"), index=True)
    step_name: Mapped[SeoFlowStep] = mapped_column(
        Enum(SeoFlowStep, name="seo_flow_step", values_callable=enum_values),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[FlowStepStatus] = mapped_column(
        Enum(FlowStepStatus, name="flow_step_status", values_callable=enum_values),
        nullable=False,
        index=True,
    )
    requested_capability: Mapped[str | None] = mapped_column(String(120), index=True)
    input_document_id: Mapped[str | None] = mapped_column(String(64))
    output_document_id: Mapped[str | None] = mapped_column(String(64))
    execution_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExecutionModel(Base):
    __tablename__ = "executions"
    __table_args__ = (UniqueConstraint("step_id", name="uq_executions_step_id"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    flow_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    requested_capability: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, name="execution_status", values_callable=enum_values),
        nullable=False,
        index=True,
    )
    bot_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("bots.id"))
    step_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("flow_steps.id"))
    input_document_id: Mapped[str | None] = mapped_column(String(64))
    output_document_id: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    internal_state: Mapped[str | None] = mapped_column(String(80), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExecutionCheckpointModel(Base):
    __tablename__ = "execution_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "checkpoint",
            name="uq_execution_checkpoints_execution_checkpoint",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    flow_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("flows.id"),
        nullable=False,
        index=True,
    )
    execution_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("executions.id"),
        nullable=False,
        index=True,
    )
    checkpoint: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    mongo_document_id: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExecutionEventModel(Base):
    __tablename__ = "execution_events"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "sequence",
            name="uq_execution_events_execution_sequence",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, unique=True)
    execution_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("executions.id"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    stage: Mapped[str | None] = mapped_column(String(80), index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PostMonitorBotModel(Base):
    __tablename__ = "post_monitor_bots"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    bot_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str | None] = mapped_column(String(80))
    environment: Mapped[str] = mapped_column(String(40), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reported_status: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    current_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outbox_pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PostMonitorEventModel(Base):
    __tablename__ = "post_monitor_events"
    __table_args__ = (
        UniqueConstraint("bot_id", "event_id", name="uq_post_monitor_events_bot_event"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    bot_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("post_monitor_bots.id"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class PostMonitorRunModel(Base):
    __tablename__ = "post_monitor_runs"
    __table_args__ = (
        UniqueConstraint("bot_id", "run_id", name="uq_post_monitor_runs_bot_run"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    bot_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("post_monitor_bots.id"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    source_event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    target_external_id: Mapped[str | None] = mapped_column(String(240), index=True)
    target_url: Mapped[str | None] = mapped_column(Text)
    target_title: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    summary: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    artifacts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PostMonitorAlertModel(Base):
    __tablename__ = "post_monitor_alerts"
    __table_args__ = (
        UniqueConstraint("bot_id", "alert_id", name="uq_post_monitor_alerts_bot_alert"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    bot_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("post_monitor_bots.id"),
        nullable=False,
        index=True,
    )
    alert_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    source_event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    observed_value: Mapped[float] = mapped_column(nullable=False)
    operator: Mapped[str] = mapped_column(String(8), nullable=False)
    threshold: Mapped[float] = mapped_column(nullable=False)
    unit: Mapped[str | None] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    rule_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    target: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PostBotWorkerModel(Base):
    """Worker del canal aislado del bot de posts (no es un `bots` del workflow)."""

    __tablename__ = "post_bot_workers"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    bot_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    bot_type: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[str | None] = mapped_column(String(80))
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(String(80)), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    session_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    available_slots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PostBotJobModel(Base):
    __tablename__ = "post_bot_jobs"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    capability: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="queued",
        index=True,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(240), unique=True, index=True)
    requested_by: Mapped[str | None] = mapped_column(String(120))
    worker_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("post_bot_workers.id"),
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PostBotJobEventModel(Base):
    __tablename__ = "post_bot_job_events"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("post_bot_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    worker_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
