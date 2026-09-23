from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, Protocol
from uuid import UUID

from orchestrator.domain.entities import (
    Bot,
    Execution,
    ExecutionCheckpoint,
    ExecutionEvent,
    ExecutionStatus,
    Flow,
    FlowStep,
)
from orchestrator.domain.page_execution import SourcePageExecution


class BotRepository(Protocol):
    async def save(self, bot: Bot) -> Bot: ...

    async def get(self, bot_id: UUID) -> Bot | None: ...

    async def get_by_key(self, bot_key: str) -> Bot | None: ...

    async def find_enabled_by_capability(self, capability: str) -> Bot | None: ...

    async def list_enabled_by_capability(self, capability: str) -> list[Bot]: ...


class ExecutionRepository(Protocol):
    async def save(self, execution: Execution) -> Execution: ...

    async def get(self, execution_id: UUID) -> Execution | None: ...

    async def list_dispatchable_for_bot(
        self,
        bot_id: UUID,
        capabilities: list[str],
        limit: int,
    ) -> list[Execution]: ...

    async def list_pending_for_bot(
        self,
        bot_id: UUID,
        capabilities: list[str],
        limit: int,
    ) -> list[Execution]: ...

    async def list_active_for_bot(self, bot_id: UUID) -> list[Execution]: ...


class ExecutionListingRepository(Protocol):
    """Lectura paginada de ejecuciones acotada a un conjunto de capabilities.

    Se mantiene aparte de ExecutionRepository porque solo la consumen las
    vistas de consulta del dashboard; los casos de uso de despacho no la
    necesitan.
    """

    async def list_by_capabilities(
        self,
        capabilities: Sequence[str],
        *,
        execution_status: ExecutionStatus | None,
        limit: int,
    ) -> tuple[list[Execution], int]: ...


class ExecutionCheckpointRepository(Protocol):
    async def create(
        self,
        checkpoint: ExecutionCheckpoint,
    ) -> tuple[ExecutionCheckpoint, bool]: ...

    async def save(self, checkpoint: ExecutionCheckpoint) -> ExecutionCheckpoint: ...

    async def get(
        self,
        execution_id: UUID,
        checkpoint: str,
    ) -> ExecutionCheckpoint | None: ...


class ExecutionEventRepository(Protocol):
    async def append(self, event: ExecutionEvent) -> tuple[str, int]: ...

    async def list_by_execution(
        self,
        execution_id: UUID,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> list[ExecutionEvent]: ...


class FlowRepository(Protocol):
    async def save(self, flow: Flow) -> Flow: ...

    async def get(self, flow_id: UUID) -> Flow | None: ...


class FlowStepRepository(Protocol):
    async def save(self, step: FlowStep) -> FlowStep: ...

    async def save_many(self, steps: list[FlowStep]) -> list[FlowStep]: ...

    async def get(self, step_id: UUID) -> FlowStep | None: ...

    async def list_by_flow(self, flow_id: UUID) -> list[FlowStep]: ...


class FlowPayloadRepository(Protocol):
    async def store(
        self,
        flow_type: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> str: ...

    async def get(self, flow_id: str) -> dict[str, Any] | None: ...


class FlowDocumentRepository(Protocol):
    async def store_document(
        self,
        flow_id: str,
        step_name: str,
        document_type: str,
        payload: Any,
        execution_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> str: ...

    async def get_document(self, document_id: str) -> dict[str, Any] | None: ...


class BotClient(Protocol):
    async def start_execution(self, base_url: str, flow_id: str, execution_id: UUID) -> None: ...


class JobQueue(Protocol):
    async def enqueue_execution(self, execution_id: UUID) -> None: ...


class BotPresenceRepository(Protocol):
    async def mark_online(
        self,
        bot: Bot,
        session_id: str,
        available_slots: int,
        ttl_seconds: int,
        deadline_seconds: int,
    ) -> None: ...

    async def heartbeat(
        self,
        bot_id: UUID,
        available_slots: int,
        current_jobs: int,
        ttl_seconds: int,
        session_id: str,
        deadline_seconds: int,
    ) -> bool: ...

    async def mark_offline(self, bot_id: UUID, session_id: str | None = None) -> bool: ...

    async def is_online(self, bot_id: UUID) -> bool: ...

    async def available_slots(self, bot_id: UUID) -> int | None: ...

    async def reserve_slot(
        self,
        bot_id: UUID,
        execution_id: UUID,
        max_concurrency: int,
    ) -> bool: ...

    async def restore_reservation(self, bot_id: UUID, execution_id: UUID) -> None: ...

    async def release_slot(self, bot_id: UUID, execution_id: UUID) -> None: ...

    async def current_session_id(self, bot_id: UUID) -> str | None: ...

    async def expired_sessions(self, now_timestamp: float) -> list[str]: ...

    async def claim_expired_session(self, member: str, now_timestamp: float) -> bool: ...

    async def reserved_execution_ids(self, bot_id: UUID) -> set[UUID]: ...

    async def bots_with_reservations(self) -> set[UUID]: ...


class BotCommandGateway(Protocol):
    async def send_execution(
        self,
        bot_id: UUID,
        flow_id: str,
        execution_id: UUID,
        capability: str,
        stage: str | None,
        input_document_id: str | None,
        command_payload: dict[str, Any] | None = None,
    ) -> None: ...

    async def send_cancel(self, bot_id: UUID, execution_id: UUID) -> None: ...


class SourcePageExecutionRepository(Protocol):
    async def get(self, queue_execution_id: int) -> SourcePageExecution | None: ...


class PageExecutionDocumentRepository(Protocol):
    async def upsert_execution(
        self, execution: SourcePageExecution, log_key: str
    ) -> dict[str, Any]: ...

    async def get_execution(self, queue_execution_id: int) -> dict[str, Any] | None: ...

    async def link_orchestrator_flow(
        self,
        queue_execution_id: int,
        flow_id: str,
        execution_id: str,
    ) -> None: ...

    async def upsert_artifact(
        self,
        execution: SourcePageExecution,
        filename: str,
        payload: Any,
    ) -> dict[str, Any]: ...

    async def upsert_artifacts(
        self,
        execution: SourcePageExecution,
        artifacts: dict[str, Any],
    ) -> list[dict[str, Any]]: ...

    async def list_artifacts(self, queue_execution_id: int) -> list[dict[str, Any]]: ...

    async def get_artifact(
        self,
        queue_execution_id: int,
        filename: str,
    ) -> dict[str, Any] | None: ...

    async def list_campaigns(self) -> list[dict[str, Any]]: ...

    async def list_pages(self, campaign_id: int) -> list[dict[str, Any]]: ...

    async def list_page_executions(self, campaign_page_id: int) -> list[dict[str, Any]]: ...


class PageExecutionLogRepository(Protocol):
    async def set_log(
        self,
        execution: SourcePageExecution,
        payload: Any,
        ttl_seconds: int,
    ) -> dict[str, Any]: ...

    async def get_log(self, log_key: str) -> dict[str, Any] | None: ...


class SeoAgentManagementRepository(Protocol):
    async def list_campaigns(self) -> list[dict[str, Any]]: ...

    async def list_admin_records(self, resource: str) -> list[dict[str, Any]]: ...

    async def create_admin_record(
        self,
        resource: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def update_admin_record(
        self,
        resource: str,
        record_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def delete_admin_record(
        self,
        resource: str,
        record_id: int,
    ) -> dict[str, Any]: ...

    async def list_services(
        self,
        campaign_id: int | None = None,
        campaign_slug: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def list_pages(
        self,
        *,
        campaign_id: int | None = None,
        campaign_slug: str | None = None,
        page_type: str | None = None,
        limit: int = 300,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...

    async def create_page(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def update_page(
        self,
        campaign_page_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def upsert_import_page(
        self,
        payload: dict[str, Any],
        campaign_page_id: int | None,
        dry_run: bool,
    ) -> tuple[dict[str, Any], str]: ...

    async def schedule_pages(
        self,
        campaign_page_ids: list[int],
        scheduled_for: date,
        notes: str,
        priority: int = 100,
    ) -> dict[str, Any]: ...

    async def list_post_groups(
        self,
        *,
        campaign_id: int | None = None,
        state: str | None = None,
        post_status: str | None = None,
        search: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]: ...

    async def create_post_group(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def update_post_group(
        self,
        group_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def delete_post_group(self, group_id: int) -> dict[str, Any]: ...

    async def list_queue(
        self,
        *,
        view: str = "all",
        campaign_id: int | None = None,
        campaign_page_id: int | None = None,
        page_type: str | None = None,
        limit: int = 150,
    ) -> list[dict[str, Any]]: ...

    async def create_run_now(
        self,
        campaign_page_id: int,
        notes: str,
    ) -> dict[str, Any]: ...

    async def retry_queue(self, queue_execution_id: int) -> dict[str, Any]: ...

    async def cancel_queue(self, queue_execution_id: int) -> dict[str, Any] | None: ...

    async def get_page(self, campaign_page_id: int) -> dict[str, Any] | None: ...

    async def update_page_wp_page_id(
        self,
        campaign_page_id: int,
        wp_page_id: int,
    ) -> None: ...

    async def get_due_queue(self, limit: int) -> list[dict[str, Any]]: ...

    async def mark_queue_running(self, queue_execution_id: int) -> bool: ...

    async def note_queue_start_error(
        self, queue_execution_id: int, error_message: str
    ) -> None: ...

    async def update_queue_result(
        self,
        queue_execution_id: int,
        *,
        status: str,
        result_status: str,
        error_message: str | None = None,
    ) -> None: ...


class RankPositionProvider(Protocol):
    async def check_position(
        self,
        *,
        url: str,
        keyword: str,
        location: str,
        country: str,
        language: str,
    ) -> dict[str, Any]: ...
