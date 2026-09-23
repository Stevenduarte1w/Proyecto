from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import orchestrator.api.v1.auth as execution_auth
from orchestrator.api.v1.auth import require_bot_execution_access
from orchestrator.api.v1.routes.bots import bot_websocket
from orchestrator.application.dtos import ExecutionProgressMessage
from orchestrator.application.use_cases.cancel_execution import (
    CancelExecution,
    CompleteExecutionCancellation,
)
from orchestrator.application.use_cases.execution_progress import (
    ExecutionProgressError,
    RecordExecutionProgress,
)
from orchestrator.core.config import Settings, get_settings
from orchestrator.domain.entities import Bot, Execution, ExecutionEvent, ExecutionStatus
from orchestrator.infrastructure.bots.auth import (
    authenticated_bot_key,
    is_page_flow_bot,
    websocket_transport_is_secure,
)


class InMemoryExecutionRepository:
    def __init__(self, execution: Execution) -> None:
        self.execution = execution

    async def get(self, execution_id: UUID) -> Execution | None:
        return self.execution if execution_id == self.execution.id else None

    async def save(self, execution: Execution) -> Execution:
        self.execution = execution
        return execution


class InMemoryBotRepository:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def get(self, bot_id: UUID) -> Bot | None:
        return self.bot if bot_id == self.bot.id else None

    async def get_by_key(self, bot_key: str) -> Bot | None:
        return self.bot if bot_key == self.bot.bot_key else None


class InMemoryEventRepository:
    def __init__(self) -> None:
        self.events: dict[int, ExecutionEvent] = {}

    async def append(self, event: ExecutionEvent) -> tuple[str, int]:
        if event.sequence in self.events:
            return "duplicate", max(self.events) + 1
        expected = max(self.events, default=0) + 1
        if event.sequence != expected:
            return "gap", expected
        self.events[event.sequence] = event
        return "stored", expected + 1


class RecordingCommandGateway:
    def __init__(self) -> None:
        self.cancelled: list[tuple[UUID, UUID]] = []

    async def send_cancel(self, bot_id: UUID, execution_id: UUID) -> None:
        self.cancelled.append((bot_id, execution_id))


class RecordingPresence:
    def __init__(self) -> None:
        self.released: list[tuple[UUID, UUID]] = []

    async def release_slot(self, bot_id: UUID, execution_id: UUID) -> None:
        self.released.append((bot_id, execution_id))


class RejectedWebSocket:
    def __init__(self, register_message: dict[str, Any]) -> None:
        self.headers: dict[str, str] = {}
        self.url = SimpleNamespace(scheme="ws")
        self.accepted = False
        self.closed: list[tuple[int, str]] = []
        self.register_message = register_message

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed.append((code, reason or ""))

    async def receive_json(self) -> dict[str, Any]:
        return self.register_message


def test_bot_bearer_resolves_only_its_bound_identity() -> None:
    settings = Settings(bot_tokens={"saaf-secret": "saaf-backlinks-01"})

    assert authenticated_bot_key("Bearer saaf-secret", settings) == "saaf-backlinks-01"
    assert authenticated_bot_key("Bearer wrong", settings) is None
    assert authenticated_bot_key(None, settings) is None


def test_only_page_flow_capabilities_may_connect_without_token() -> None:
    assert is_page_flow_bot(["wordpress.page_upsert"])
    assert is_page_flow_bot(
        [
            "seo.main",
            "posts.create",
            "video.create",
            "pagespeed.check",
            "indexing.submit",
        ]
    )
    assert not is_page_flow_bot([])
    assert not is_page_flow_bot(["backlinks.saaf"])
    assert not is_page_flow_bot(["seo.main", "backlinks.saaf"])


def test_production_requires_secure_websocket_transport() -> None:
    assert not websocket_transport_is_secure(
        app_env="production",
        websocket_scheme="ws",
        forwarded_proto=None,
    )
    assert websocket_transport_is_secure(
        app_env="production",
        websocket_scheme="ws",
        forwarded_proto="https",
    )
    assert websocket_transport_is_secure(
        app_env="local",
        websocket_scheme="ws",
        forwarded_proto=None,
    )


async def test_non_page_websocket_without_bearer_is_rejected_after_register() -> None:
    get_settings.cache_clear()
    websocket = RejectedWebSocket(
        {
            "type": "bot.register",
            "bot_key": "mails-maturation-vm01",
            "name": "Mail maturation",
            "bot_type": "emails",
            "capabilities": ["emails.maturation"],
        }
    )

    await bot_websocket(cast(Any, websocket), cast(Any, None))

    assert websocket.accepted
    assert websocket.closed == [(4401, "Invalid bot credentials")]


async def test_non_page_execution_document_route_requires_bot_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = Execution(
        flow_id=str(uuid4()),
        requested_capability="backlinks.saaf",
        step_id=uuid4(),
    )
    monkeypatch.setattr(
        execution_auth,
        "SqlAlchemyExecutionRepository",
        lambda _session: InMemoryExecutionRepository(execution),
    )
    request = Request({"type": "http", "headers": []})

    with pytest.raises(HTTPException) as error:
        await require_bot_execution_access(execution.id, request, cast(Any, None))

    assert error.value.status_code == 401


async def test_page_flow_execution_document_route_does_not_require_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = Bot(
        name="WordPress Page Setup",
        bot_key="wordpress-page-setup-01",
        bot_type="wordpress",
        capabilities=["wordpress.page_upsert"],
    )
    execution = Execution(
        flow_id=str(uuid4()),
        requested_capability="wordpress.page_upsert",
        bot_id=bot.id,
        step_id=uuid4(),
    )
    monkeypatch.setattr(
        execution_auth,
        "SqlAlchemyExecutionRepository",
        lambda _session: InMemoryExecutionRepository(execution),
    )
    monkeypatch.setattr(
        execution_auth,
        "SqlAlchemyBotRepository",
        lambda _session: InMemoryBotRepository(bot),
    )
    request = Request({"type": "http", "headers": []})

    principal = await require_bot_execution_access(
        execution.id,
        request,
        cast(Any, None),
    )

    assert principal.bot_id == bot.id
    assert principal.bot_key == bot.bot_key


def test_standalone_execution_is_not_part_of_tokenless_page_flow() -> None:
    execution = Execution(
        flow_id="standalone-pagespeed",
        requested_capability="pagespeed.check",
        step_id=None,
    )

    assert not execution_auth._allows_tokenless_page_flow_access(execution)


async def test_progress_is_ordered_idempotent_and_updates_stage() -> None:
    bot_id = uuid4()
    execution = Execution(
        flow_id=str(uuid4()),
        requested_capability="backlinks.saaf",
        status=ExecutionStatus.RUNNING,
        bot_id=bot_id,
    )
    executions = InMemoryExecutionRepository(execution)
    events = InMemoryEventRepository()
    recorder = RecordExecutionProgress(executions, events)  # type: ignore[arg-type]
    first = ExecutionProgressMessage(
        type="execution.progress",
        event_id=uuid4(),
        execution_id=execution.id,
        sequence=1,
        event_type="stage.start",
        stage="prefiltro",
        summary="Iniciando prefiltro",
    )

    stored = await recorder.execute(first, bot_id)
    duplicate = await recorder.execute(first, bot_id)
    gap = await recorder.execute(
        first.model_copy(update={"event_id": uuid4(), "sequence": 3}),
        bot_id,
    )

    assert stored.status == "stored"
    assert duplicate.status == "duplicate"
    assert gap.status == "gap"
    assert gap.expected_sequence == 2
    assert execution.internal_state == "prefiltro"


async def test_stage_end_requires_input_and_output_counts() -> None:
    bot_id = uuid4()
    execution = Execution(
        flow_id=str(uuid4()),
        requested_capability="backlinks.saaf",
        status=ExecutionStatus.RUNNING,
        bot_id=bot_id,
    )
    recorder = RecordExecutionProgress(
        InMemoryExecutionRepository(execution),
        InMemoryEventRepository(),
    )
    message = ExecutionProgressMessage(
        type="execution.progress",
        event_id=uuid4(),
        execution_id=execution.id,
        sequence=1,
        event_type="stage.end",
        stage="prefiltro",
        payload={"in": 100},
    )

    with pytest.raises(ExecutionProgressError, match="payload.in and payload.out"):
        await recorder.execute(message, bot_id)


async def test_cooperative_cancellation_is_idempotent_until_bot_confirms() -> None:
    bot_id = uuid4()
    execution = Execution(
        flow_id=str(uuid4()),
        requested_capability="backlinks.saaf",
        status=ExecutionStatus.RUNNING,
        bot_id=bot_id,
    )
    executions = InMemoryExecutionRepository(execution)
    commands = RecordingCommandGateway()
    cancel = CancelExecution(executions, commands)  # type: ignore[arg-type]

    first = await cancel.execute(execution.id)
    second = await cancel.execute(execution.id)

    assert first is not None and first.status is ExecutionStatus.CANCELLING
    assert second is not None and second.status is ExecutionStatus.CANCELLING
    assert commands.cancelled == [(bot_id, execution.id)]
    assert execution.completed_at is None

    presence = RecordingPresence()
    completed = await CompleteExecutionCancellation(  # type: ignore[arg-type]
        executions,
        presence,
    ).execute(execution.id, bot_id)

    assert completed.status is ExecutionStatus.CANCELLED
    assert presence.released == [(bot_id, execution.id)]
