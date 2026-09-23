from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from orchestrator.domain.entities import ExecutionStatus, FlowStatus, FlowStepStatus, SeoFlowStep
from orchestrator.domain.instagram import (
    INSTAGRAM_MADURACION_CAPABILITY,
    INSTAGRAM_PROSPECTING_CAPABILITY,
)


class BotCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    bot_key: str = Field(min_length=2, max_length=120)
    bot_type: str = Field(min_length=2, max_length=80)
    base_url: AnyHttpUrl | None = None
    capabilities: list[str] = Field(default_factory=list)
    version: str | None = None
    max_concurrency: int = Field(default=1, ge=1, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class BotResponse(BaseModel):
    id: UUID
    name: str
    bot_key: str
    bot_type: str
    base_url: str | None = None
    capabilities: list[str]
    version: str | None = None
    max_concurrency: int
    metadata: dict[str, Any]
    enabled: bool
    last_seen_at: datetime | None = None


class BotRegisterMessage(BaseModel):
    type: str = Field(default="bot.register")
    bot_key: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=120)
    bot_type: str = Field(min_length=2, max_length=80)
    capabilities: list[str] = Field(min_length=1)
    version: str | None = None
    max_concurrency: int = Field(default=1, ge=1, le=100)
    available_slots: int = Field(default=1, ge=0, le=100)
    active_executions: list[UUID] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BotHeartbeatMessage(BaseModel):
    type: str = Field(default="bot.heartbeat")
    current_jobs: int = Field(default=0, ge=0)
    available_slots: int = Field(default=1, ge=0)


class WordpressPageSetupRequest(BaseModel):
    action: Literal["create", "update", "skip"] = "skip"
    slug: str = Field(min_length=1, max_length=300)
    wp_page_id: int | None = Field(default=None, gt=0)
    campaign_id: int | None = Field(default=None, gt=0)

    @field_validator("slug")
    @classmethod
    def normalize_registered_slug(cls, value: str) -> str:
        normalized = value.strip().strip("/")
        if not normalized or "/" in normalized or "\\" in normalized:
            raise ValueError("slug must be a single non-empty path segment")
        return normalized

    @model_validator(mode="after")
    def validate_action_identifiers(self) -> WordpressPageSetupRequest:
        if self.action in {"create", "update"} and self.campaign_id is None:
            raise ValueError(
                "campaign_id is required when page setup action is create or update"
            )
        if self.action == "update" and self.wp_page_id is None:
            raise ValueError("wp_page_id is required when page setup action is update")
        return self
class BacklinksCompanyCatalogItem(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    nombre: str = Field(min_length=1, max_length=240)
    nicho: str = Field(min_length=1, max_length=120)
    url: AnyHttpUrl


class BotCatalogUpdatedMessage(BaseModel):
    type: Literal["bot.catalog.updated"]
    catalog_version: str = Field(min_length=1, max_length=128)
    companies: list[BacklinksCompanyCatalogItem] = Field(max_length=1_000)


class BacklinksCatalogResponse(BaseModel):
    bot_id: UUID
    bot_key: str
    online: bool
    catalog_version: str
    companies: list[BacklinksCompanyCatalogItem]


class ExecutionProgressMessage(BaseModel):
    type: Literal["execution.progress"]
    event_id: UUID
    execution_id: UUID
    sequence: int = Field(ge=1)
    event_type: Literal[
        "run.start",
        "stage.start",
        "stage.end",
        "site.start",
        "site.done",
        "stats",
        "log",
        "run.end",
        "error",
    ]
    stage: str | None = Field(default=None, max_length=80)
    summary: str | None = Field(default=None, max_length=1_000)
    payload: dict[str, Any] = Field(default_factory=dict)


class FlowSubmitRequest(BaseModel):
    flow_type: str = Field(min_length=2, max_length=80)
    queue_execution_id: int = Field(gt=0)
    campaign_page_id: int = Field(gt=0)
    page_url: AnyHttpUrl
    campaign: str | None = Field(default=None, max_length=120)
    commercial_objective: str | None = Field(default=None, max_length=500)
    payload: dict[str, Any]
    requested_capability: str = "seo.main"
    correlation_id: str | None = None
    preferred_bot_id: UUID | None = None
    page_setup: WordpressPageSetupRequest | None = None


class FlowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    flow_type: str
    page_url: str
    campaign: str | None = None
    commercial_objective: str | None = None
    status: FlowStatus
    current_step: SeoFlowStep
    initial_document_id: str | None = None
    correlation_id: str | None = None
    created_at: datetime
    updated_at: datetime


class FlowStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    flow_id: UUID
    step_name: SeoFlowStep
    position: int
    status: FlowStepStatus
    requested_capability: str | None = None
    input_document_id: str | None = None
    output_document_id: str | None = None
    execution_id: UUID | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class DispatchExecutionRequest(BaseModel):
    execution_id: UUID
    preferred_bot_id: UUID | None = None


class StandalonePageSpeedRequest(BaseModel):
    page_url: AnyHttpUrl
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = Field(default=None, max_length=120)


class InstagramTargets(BaseModel):
    mode: Literal["accounts", "owner", "all"]
    account_ids: list[int] | None = None
    owner_id: int | None = None

    @model_validator(mode="after")
    def validate_target_selection(self) -> InstagramTargets:
        if self.mode == "accounts" and not self.account_ids:
            raise ValueError("targets.account_ids is required when targets.mode is accounts")
        if self.mode == "owner" and self.owner_id is None:
            raise ValueError("targets.owner_id is required when targets.mode is owner")
        return self


class StandaloneInstagramRequest(BaseModel):
    schema_version: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    capability: str
    task_types: list[StrictInt] = Field(min_length=1)
    targets: InstagramTargets
    custom_task: dict[str, Any] | None = None
    schedule: dict[str, Any] | None = None
    options: dict[str, Any] | None = None

    @field_validator("capability")
    @classmethod
    def validate_capability(cls, value: str) -> str:
        if value not in {
            INSTAGRAM_MADURACION_CAPABILITY,
            INSTAGRAM_PROSPECTING_CAPABILITY,
        }:
            raise ValueError("unsupported Instagram capability")
        return value


class ExecutionResultRequest(BaseModel):
    status: ExecutionStatus = ExecutionStatus.SUCCEEDED
    payload: dict[str, Any] | bool = Field(default_factory=dict)
    error: str | None = None


class ExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    flow_id: str
    requested_capability: str
    status: ExecutionStatus
    bot_id: UUID | None = None
    step_id: UUID | None = None
    input_document_id: str | None = None
    output_document_id: str | None = None
    error_message: str | None = None
    internal_state: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExecutionSummaryResponse(BaseModel):
    """Vista reducida para listados del dashboard.

    Deja fuera los ids de documento, el error y el internal_state: son detalle
    interno y no hacen falta para pintar un historial.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    requested_capability: str
    status: ExecutionStatus
    bot_id: UUID | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class ExecutionListResponse(BaseModel):
    items: list[ExecutionSummaryResponse]
    total: int


class ExecutionEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    execution_id: UUID
    sequence: int
    event_type: str
    stage: str | None = None
    summary: str | None = None
    payload: dict[str, Any]
    created_at: datetime


class FlowSubmitResponse(BaseModel):
    flow: FlowResponse
    steps: list[FlowStepResponse]
    initial_execution: ExecutionResponse
    dispatched_initial_execution: ExecutionResponse | None = None


class WorkflowAdvanceResponse(BaseModel):
    flow: FlowResponse
    created_executions: list[ExecutionResponse] = Field(default_factory=list)
    dispatched_executions: list[ExecutionResponse] = Field(default_factory=list)
    pending_dispatch_executions: list[ExecutionResponse] = Field(default_factory=list)
    waiting_approval_step: FlowStepResponse | None = None
    completed: bool = False


class ExecutionCompletionResponse(BaseModel):
    execution: ExecutionResponse
    workflow: WorkflowAdvanceResponse | None = None


class ExecutionCheckpointResponse(BaseModel):
    execution: ExecutionResponse
    checkpoint: str
    duplicate: bool = False
    created_executions: list[ExecutionResponse] = Field(default_factory=list)
    dispatched_executions: list[ExecutionResponse] = Field(default_factory=list)
