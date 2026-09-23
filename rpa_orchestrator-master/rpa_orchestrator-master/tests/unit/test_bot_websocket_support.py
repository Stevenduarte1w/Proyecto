from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

from orchestrator.application.dtos import BotRegisterMessage
from orchestrator.application.use_cases.reconcile_bot_connections import (
    ReconcileBotConnections,
)
from orchestrator.core.config import Settings
from orchestrator.domain.entities import Execution, ExecutionStatus
from orchestrator.infrastructure.bots.auth import bot_registration_is_authorized
from orchestrator.infrastructure.bots.ws_manager import BotWebSocketManager


@asynccontextmanager
async def always_lock(key: str, ttl_seconds: int) -> AsyncIterator[bool]:
    yield True


class ExecutionRepository:
    def __init__(self, executions: list[Execution]) -> None:
        self.executions = {execution.id: execution for execution in executions}

    async def get(self, execution_id: UUID) -> Execution | None:
        return self.executions.get(execution_id)

    async def save(self, execution: Execution) -> Execution:
        self.executions[execution.id] = execution
        return execution

    async def list_active_for_bot(self, bot_id: UUID) -> list[Execution]:
        return [
            execution
            for execution in self.executions.values()
            if execution.bot_id == bot_id
            and execution.status in {ExecutionStatus.QUEUED, ExecutionStatus.RUNNING}
        ]


class PresenceRepository:
    def __init__(self) -> None:
        self.reservations: dict[UUID, set[UUID]] = {}
        self.released: list[tuple[UUID, UUID]] = []

    async def restore_reservation(self, bot_id: UUID, execution_id: UUID) -> None:
        self.reservations.setdefault(bot_id, set()).add(execution_id)

    async def release_slot(self, bot_id: UUID, execution_id: UUID) -> None:
        self.reservations.setdefault(bot_id, set()).discard(execution_id)
        self.released.append((bot_id, execution_id))


class ReconnectRacePresence(PresenceRepository):
    def __init__(self, bot_id: UUID, session_id: str) -> None:
        super().__init__()
        self.bot_id = bot_id
        self.session_id = session_id

    async def expired_sessions(self, now_timestamp: float) -> list[str]:
        return [f"{self.bot_id}:{self.session_id}"]

    async def claim_expired_session(self, member: str, now_timestamp: float) -> bool:
        return True

    async def current_session_id(self, bot_id: UUID) -> str | None:
        return self.session_id

    async def mark_offline(self, bot_id: UUID, session_id: str | None = None) -> bool:
        # Simulates a new session replacing the old one after current_session_id().
        return False


class FakeWebSocket:
    def __init__(self) -> None:
        self.closed: list[tuple[int, str]] = []
        self.messages: list[dict[str, Any]] = []

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed.append((code, reason or ""))

    async def send_json(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


def test_bot_token_is_bound_to_registered_bot_key() -> None:
    settings = Settings(
        bot_tokens={"worker-secret": "mails-maturation-vm01"},
    )

    assert bot_registration_is_authorized(
        "Bearer worker-secret",
        "mails-maturation-vm01",
        settings,
    )
    assert not bot_registration_is_authorized(
        "Bearer worker-secret",
        "another-bot",
        settings,
    )
    assert not bot_registration_is_authorized(None, "legacy-seo-01", settings)
    assert not bot_registration_is_authorized(None, "mails-maturation-vm01", settings)


def test_register_message_accepts_optional_active_executions() -> None:
    execution_id = uuid4()
    message = BotRegisterMessage.model_validate(
        {
            "type": "bot.register",
            "bot_key": "mails-maturation-vm01",
            "name": "Mail maturation",
            "bot_type": "emails",
            "capabilities": ["emails.maturation"],
            "active_executions": [str(execution_id)],
        }
    )

    assert message.active_executions == [execution_id]


async def test_reconnect_preserves_declared_work_and_resolves_missing_work() -> None:
    bot_id = uuid4()
    declared_running = Execution(
        flow_id="running",
        requested_capability="emails.maturation",
        status=ExecutionStatus.RUNNING,
        bot_id=bot_id,
    )
    missing_queued = Execution(
        flow_id="queued",
        requested_capability="emails.maturation",
        status=ExecutionStatus.QUEUED,
        bot_id=bot_id,
    )
    stale_terminal = Execution(
        flow_id="done",
        requested_capability="emails.maturation",
        status=ExecutionStatus.SUCCEEDED,
        bot_id=bot_id,
    )
    executions = ExecutionRepository([declared_running, missing_queued, stale_terminal])
    presence = PresenceRepository()
    reconciler = ReconcileBotConnections(executions, presence)  # type: ignore[arg-type]

    stale = await reconciler.reconcile_registration(
        bot_id,
        [declared_running.id, stale_terminal.id],
    )

    assert stale == [stale_terminal.id]
    assert declared_running.status is ExecutionStatus.RUNNING
    assert declared_running.id in presence.reservations[bot_id]
    assert missing_queued.status is ExecutionStatus.PENDING
    assert missing_queued.bot_id is None
    assert (bot_id, missing_queued.id) in presence.released


async def test_legacy_registration_does_not_reconcile_unknown_active_work() -> None:
    bot_id = uuid4()
    running = Execution(
        flow_id="running",
        requested_capability="seo.main",
        status=ExecutionStatus.RUNNING,
        bot_id=bot_id,
    )
    executions = ExecutionRepository([running])
    presence = PresenceRepository()

    stale = await ReconcileBotConnections(  # type: ignore[arg-type]
        executions,
        presence,
    ).reconcile_registration(bot_id, None)

    assert stale == []
    assert running.status is ExecutionStatus.RUNNING
    assert presence.released == []


async def test_reconciliation_race_does_not_fail_new_session_work() -> None:
    bot_id = uuid4()
    session_id = str(uuid4())
    running = Execution(
        flow_id="running",
        requested_capability="emails.maturation",
        status=ExecutionStatus.RUNNING,
        bot_id=bot_id,
    )
    executions = ExecutionRepository([running])
    presence = ReconnectRacePresence(bot_id, session_id)

    await ReconcileBotConnections(  # type: ignore[arg-type]
        executions,
        presence,
        lock_factory=always_lock,
    ).reconcile_expired_sessions()

    assert running.status is ExecutionStatus.RUNNING
    assert presence.released == []


async def test_new_websocket_session_cannot_be_removed_by_old_session() -> None:
    bot_id = uuid4()
    first = FakeWebSocket()
    second = FakeWebSocket()
    manager = BotWebSocketManager()

    await manager.connect(bot_id, "session-1", first)  # type: ignore[arg-type]
    await manager.connect(bot_id, "session-2", second)  # type: ignore[arg-type]
    await manager.disconnect(bot_id, "session-1")

    assert first.closed == [(1012, "Bot opened a newer session")]
    assert manager.is_connected(bot_id)

    await manager.disconnect(bot_id, "session-2")
    assert not manager.is_connected(bot_id)
