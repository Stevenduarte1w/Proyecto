from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionCheckpointStatus(StrEnum):
    RECEIVED = "received"
    PROCESSED = "processed"
    FAILED = "failed"


class FlowStatus(StrEnum):
    RECEIVED = "received"
    IN_PROGRESS = "in_progress"
    WAITING_EXTERNAL = "waiting_external"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FlowStepStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    WAITING_APPROVAL = "waiting_approval"


class SeoFlowStep(StrEnum):
    WORDPRESS_PAGE_SETUP = "wordpress_page_setup"
    CONTEXT_BUILDING = "context_building"
    WORDPRESS_EXTRACTION = "wordpress_extraction"
    COMPETITOR_ANALYSIS = "competitor_analysis"
    SEO_AUDIT = "seo_audit"
    WORK_PLAN = "work_plan"
    SERVICE_IMAGES = "service_images"
    MAIN_PAGE_FIX = "main_page_fix"
    SUPPORT_POSTS = "support_posts"
    VIDEO_REQUEST = "video_request"
    EXTERNAL_ASSETS_RECEIVED = "external_assets_received"
    AUTO_REVIEW = "auto_review"
    APPROVAL = "approval"
    WORDPRESS_PUBLISH = "wordpress_publish"
    POST_PUBLISH_CHECK = "post_publish_check"
    PAGESPEED = "pagespeed"
    INDEXING = "indexing"
    FINAL_REPORT = "final_report"


SEO_WORKFLOW_STEPS: tuple[SeoFlowStep, ...] = (
    SeoFlowStep.WORDPRESS_PAGE_SETUP,
    SeoFlowStep.SEO_AUDIT,
    SeoFlowStep.SUPPORT_POSTS,
    SeoFlowStep.VIDEO_REQUEST,
    SeoFlowStep.WORDPRESS_PUBLISH,
    SeoFlowStep.PAGESPEED,
    SeoFlowStep.INDEXING,
)


@dataclass(slots=True)
class Bot:
    name: str
    bot_key: str
    bot_type: str
    capabilities: list[str] = field(default_factory=list)
    base_url: str | None = None
    version: str | None = None
    max_concurrency: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_seen_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)

    def mark_seen(self) -> None:
        self.last_seen_at = datetime.now(UTC)


@dataclass(slots=True)
class Flow:
    flow_type: str
    page_url: str
    campaign: str | None = None
    commercial_objective: str | None = None
    status: FlowStatus = FlowStatus.RECEIVED
    current_step: SeoFlowStep = SeoFlowStep.SEO_AUDIT
    initial_document_id: str | None = None
    correlation_id: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def mark_in_progress(self) -> None:
        self.status = FlowStatus.IN_PROGRESS
        self._touch()

    def mark_waiting_external(self) -> None:
        self.status = FlowStatus.WAITING_EXTERNAL
        self._touch()

    def mark_waiting_approval(self) -> None:
        self.status = FlowStatus.WAITING_APPROVAL
        self.current_step = SeoFlowStep.APPROVAL
        self._touch()

    def mark_succeeded(self) -> None:
        self.status = FlowStatus.SUCCEEDED
        self.current_step = SeoFlowStep.FINAL_REPORT
        self._touch()

    def mark_failed(self) -> None:
        self.status = FlowStatus.FAILED
        self._touch()

    def move_to_step(self, step_name: SeoFlowStep) -> None:
        self.current_step = step_name
        self.mark_in_progress()

    def _touch(self) -> None:
        self.updated_at = datetime.now(UTC)


@dataclass(slots=True)
class FlowStep:
    flow_id: UUID
    step_name: SeoFlowStep
    position: int
    status: FlowStepStatus = FlowStepStatus.PENDING
    requested_capability: str | None = None
    input_document_id: str | None = None
    output_document_id: str | None = None
    execution_id: UUID | None = None
    error_message: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def assign_execution(self, execution_id: UUID) -> None:
        self.execution_id = execution_id
        self.status = FlowStepStatus.QUEUED
        self._touch()

    def mark_waiting_approval(self) -> None:
        self.status = FlowStepStatus.WAITING_APPROVAL
        self._touch()

    def mark_running(self) -> None:
        self.status = FlowStepStatus.RUNNING
        self.started_at = self.started_at or datetime.now(UTC)
        self._touch()

    def mark_skipped(self, output_document_id: str | None = None) -> None:
        self.status = FlowStepStatus.SKIPPED
        self.output_document_id = output_document_id
        self.completed_at = datetime.now(UTC)
        self.error_message = None
        self._touch()

    def mark_succeeded(self, output_document_id: str | None = None) -> None:
        self.status = FlowStepStatus.SUCCEEDED
        self.output_document_id = output_document_id
        self.completed_at = datetime.now(UTC)
        self.error_message = None
        self._touch()

    def mark_failed(self, reason: str, output_document_id: str | None = None) -> None:
        self.status = FlowStepStatus.FAILED
        self.output_document_id = output_document_id
        self.error_message = reason
        self.completed_at = datetime.now(UTC)
        self._touch()

    def _touch(self) -> None:
        self.updated_at = datetime.now(UTC)


@dataclass(slots=True)
class Execution:
    flow_id: str
    requested_capability: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    bot_id: UUID | None = None
    step_id: UUID | None = None
    input_document_id: str | None = None
    output_document_id: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error_message: str | None = None
    internal_state: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def assign_bot(self, bot_id: UUID) -> None:
        self.bot_id = bot_id
        self._touch()

    def mark_queued(self) -> None:
        self.status = ExecutionStatus.QUEUED
        self._touch()

    def return_to_pending(self) -> None:
        self.status = ExecutionStatus.PENDING
        self.bot_id = None
        self.error_message = None
        self.internal_state = None
        self.started_at = None
        self.completed_at = None
        self._touch()

    def mark_running(self, internal_state: str | None = None) -> None:
        self.status = ExecutionStatus.RUNNING
        self.internal_state = internal_state or self.internal_state
        self.started_at = self.started_at or datetime.now(UTC)
        self._touch()

    def set_internal_state(self, internal_state: str) -> None:
        self.internal_state = internal_state
        self._touch()

    def mark_cancelling(self) -> None:
        self.status = ExecutionStatus.CANCELLING
        self.internal_state = "cancelling"
        self._touch()

    def mark_cancelled(self) -> None:
        self.status = ExecutionStatus.CANCELLED
        self.internal_state = "cancelled"
        self.completed_at = datetime.now(UTC)
        self._touch()

    def mark_succeeded(self) -> None:
        self.status = ExecutionStatus.SUCCEEDED
        self.error_message = None
        self.completed_at = datetime.now(UTC)
        self._touch()

    def mark_succeeded_with_output(self, output_document_id: str | None = None) -> None:
        self.output_document_id = output_document_id
        self.mark_succeeded()

    def mark_failed(self, reason: str, output_document_id: str | None = None) -> None:
        self.status = ExecutionStatus.FAILED
        self.error_message = reason
        self.output_document_id = output_document_id
        self.completed_at = datetime.now(UTC)
        self._touch()

    def _touch(self) -> None:
        self.updated_at = datetime.now(UTC)


@dataclass(slots=True)
class ExecutionCheckpoint:
    flow_id: UUID
    execution_id: UUID
    checkpoint: str
    status: ExecutionCheckpointStatus = ExecutionCheckpointStatus.RECEIVED
    mongo_document_id: str | None = None
    error_message: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    processed_at: datetime | None = None

    def mark_processed(self) -> None:
        self.status = ExecutionCheckpointStatus.PROCESSED
        self.error_message = None
        self.processed_at = datetime.now(UTC)

    def mark_failed(self, reason: str) -> None:
        self.status = ExecutionCheckpointStatus.FAILED
        self.error_message = reason
        self.processed_at = datetime.now(UTC)


@dataclass(slots=True)
class ExecutionEvent:
    execution_id: UUID
    event_id: UUID
    sequence: int
    event_type: str
    stage: str | None = None
    summary: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
