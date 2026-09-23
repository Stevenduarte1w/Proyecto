from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.application.post_monitor import (
    PostMonitorEventConflictError,
    PostMonitorEventReceipt,
    PostMonitorHeartbeatMessage,
    PostMonitorProjectionConflictError,
    PostMonitorRegisterMessage,
    PostMonitorRunResultMessage,
    PostMonitorThresholdAlertMessage,
)
from orchestrator.infrastructure.postgres.models import (
    PostMonitorAlertModel,
    PostMonitorBotModel,
    PostMonitorEventModel,
    PostMonitorRunModel,
)


class SqlAlchemyPostMonitorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register_bot(self, message: PostMonitorRegisterMessage) -> dict[str, Any]:
        statement = select(PostMonitorBotModel).where(
            PostMonitorBotModel.bot_key == message.bot_key
        )
        result = await self._session.execute(statement)
        bot = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if bot is None:
            bot = PostMonitorBotModel(
                id=uuid4(),
                bot_key=message.bot_key,
                name=message.name,
                version=message.version,
                environment=message.environment,
                metadata_json=message.metadata,
                enabled=True,
                reported_status="idle",
                current_jobs=0,
                outbox_pending=0,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
            self._session.add(bot)
        else:
            if not bot.enabled:
                raise PermissionError("Post monitor bot is disabled")
            bot.name = message.name
            bot.version = message.version
            bot.environment = message.environment
            bot.metadata_json = message.metadata
            bot.last_seen_at = now
            bot.updated_at = now
        await self._session.commit()
        return _bot_dict(bot)

    async def heartbeat(
        self,
        bot_id: UUID,
        message: PostMonitorHeartbeatMessage,
    ) -> None:
        bot = await self._session.get(PostMonitorBotModel, bot_id)
        if bot is None or not bot.enabled:
            raise PermissionError("Post monitor bot is not available")
        now = datetime.now(UTC)
        bot.reported_status = message.status
        bot.current_jobs = message.current_jobs
        bot.outbox_pending = message.outbox_pending
        bot.last_seen_at = now
        bot.updated_at = now
        await self._session.commit()

    async def ingest_result(
        self,
        bot_id: UUID,
        message: PostMonitorRunResultMessage,
    ) -> PostMonitorEventReceipt:
        raw, payload_hash = _serialized_event(message)
        existing = await self._existing_receipt(bot_id, message.event_id, payload_hash)
        if existing is not None:
            return existing

        existing_run = await self._session.execute(
            select(PostMonitorRunModel.id).where(
                PostMonitorRunModel.bot_id == bot_id,
                PostMonitorRunModel.run_id == message.payload.run_id,
            )
        )
        if existing_run.scalar_one_or_none() is not None:
            raise PostMonitorProjectionConflictError(
                "run_id already exists with a different event_id"
            )

        now = datetime.now(UTC)
        target = message.payload.target
        event = PostMonitorEventModel(
            id=uuid4(),
            bot_id=bot_id,
            event_id=message.event_id,
            event_type=message.type,
            schema_version=message.schema_version,
            occurred_at=message.occurred_at,
            received_at=now,
            payload_hash=payload_hash,
            raw_payload=raw,
        )
        run = PostMonitorRunModel(
            id=uuid4(),
            bot_id=bot_id,
            run_id=message.payload.run_id,
            source_event_id=message.event_id,
            status=message.payload.status,
            target_external_id=target.external_id,
            target_url=target.url,
            target_title=target.title,
            started_at=message.payload.started_at,
            finished_at=message.payload.finished_at,
            duration_ms=message.payload.duration_ms,
            summary=message.payload.summary,
            metrics=message.payload.metrics,
            result=message.payload.result,
            error=(
                message.payload.error.model_dump(mode="json")
                if message.payload.error is not None
                else None
            ),
            artifacts=[item.model_dump(mode="json") for item in message.payload.artifacts],
            created_at=now,
        )
        self._session.add_all((event, run))
        return await self._commit_event(bot_id, message.event_id, payload_hash, now)

    async def ingest_alert(
        self,
        bot_id: UUID,
        message: PostMonitorThresholdAlertMessage,
    ) -> PostMonitorEventReceipt:
        raw, payload_hash = _serialized_event(message)
        existing = await self._existing_receipt(bot_id, message.event_id, payload_hash)
        if existing is not None:
            return existing

        existing_alert = await self._session.execute(
            select(PostMonitorAlertModel.id).where(
                PostMonitorAlertModel.bot_id == bot_id,
                PostMonitorAlertModel.alert_id == message.payload.alert_id,
            )
        )
        if existing_alert.scalar_one_or_none() is not None:
            raise PostMonitorProjectionConflictError(
                "alert_id already exists with a different event_id"
            )

        now = datetime.now(UTC)
        event = PostMonitorEventModel(
            id=uuid4(),
            bot_id=bot_id,
            event_id=message.event_id,
            event_type=message.type,
            schema_version=message.schema_version,
            occurred_at=message.occurred_at,
            received_at=now,
            payload_hash=payload_hash,
            raw_payload=raw,
        )
        alert = PostMonitorAlertModel(
            id=uuid4(),
            bot_id=bot_id,
            alert_id=message.payload.alert_id,
            run_id=message.payload.run_id,
            source_event_id=message.event_id,
            severity=message.payload.severity,
            metric=message.payload.metric,
            observed_value=message.payload.observed_value,
            operator=message.payload.operator,
            threshold=message.payload.threshold,
            unit=message.payload.unit,
            message=message.payload.message,
            rule_snapshot=message.payload.rule.model_dump(mode="json"),
            target=message.payload.target.model_dump(mode="json"),
            details=message.payload.details,
            status="open",
            occurred_at=message.occurred_at,
            acknowledged_at=None,
            resolved_at=None,
            created_at=now,
        )
        self._session.add_all((event, alert))
        return await self._commit_event(bot_id, message.event_id, payload_hash, now)

    async def overview(self, presence_ttl_seconds: int) -> dict[str, Any]:
        now = datetime.now(UTC)
        since = now - timedelta(hours=24)
        bot_result = await self._session.execute(
            select(PostMonitorBotModel)
            .order_by(PostMonitorBotModel.last_seen_at.desc().nulls_last())
            .limit(1)
        )
        bot = bot_result.scalar_one_or_none()

        run_counts_result = await self._session.execute(
            select(PostMonitorRunModel.status, func.count(PostMonitorRunModel.id))
            .where(PostMonitorRunModel.finished_at >= since)
            .group_by(PostMonitorRunModel.status)
        )
        run_counts = {str(status): int(count) for status, count in run_counts_result.all()}
        alert_counts_result = await self._session.execute(
            select(PostMonitorAlertModel.severity, func.count(PostMonitorAlertModel.id))
            .where(PostMonitorAlertModel.status == "open")
            .group_by(PostMonitorAlertModel.severity)
        )
        alert_counts = {
            str(severity): int(count) for severity, count in alert_counts_result.all()
        }
        latest_alert_at = await self._session.scalar(
            select(func.max(PostMonitorAlertModel.occurred_at)).where(
                PostMonitorAlertModel.status == "open"
            )
        )
        latest_run_result = await self._session.execute(
            select(PostMonitorRunModel)
            .order_by(PostMonitorRunModel.finished_at.desc())
            .limit(1)
        )
        latest_run = latest_run_result.scalar_one_or_none()
        total_runs = sum(run_counts.values())
        total_open_alerts = sum(alert_counts.values())
        bot_view = None
        if bot is not None:
            is_online = bool(
                bot.enabled
                and bot.last_seen_at is not None
                and bot.last_seen_at >= now - timedelta(seconds=presence_ttl_seconds)
            )
            bot_view = {
                **_bot_dict(bot),
                "connection_status": "online" if is_online else "offline",
            }
        return {
            "bot": bot_view,
            "runs": {
                "last_24h": total_runs,
                "succeeded": run_counts.get("succeeded", 0),
                "failed": run_counts.get("failed", 0),
                "partial": run_counts.get("partial", 0),
                "cancelled": run_counts.get("cancelled", 0),
            },
            "alerts": {
                "open": total_open_alerts,
                "critical": alert_counts.get("critical", 0),
                "warning": alert_counts.get("warning", 0),
                "info": alert_counts.get("info", 0),
                "latest_at": latest_alert_at,
            },
            "latest_metrics": dict(latest_run.metrics) if latest_run is not None else {},
        }

    async def list_runs(
        self,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        statement = select(PostMonitorRunModel).order_by(
            PostMonitorRunModel.finished_at.desc()
        )
        if status:
            statement = statement.where(PostMonitorRunModel.status == status)
        result = await self._session.execute(statement.limit(limit))
        return [_run_dict(model) for model in result.scalars().all()]

    async def list_alerts(
        self,
        status: str | None,
        severity: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        statement = select(PostMonitorAlertModel).order_by(
            PostMonitorAlertModel.occurred_at.desc()
        )
        if status:
            statement = statement.where(PostMonitorAlertModel.status == status)
        if severity:
            statement = statement.where(PostMonitorAlertModel.severity == severity)
        result = await self._session.execute(statement.limit(limit))
        return [_alert_dict(model) for model in result.scalars().all()]

    async def update_alert(
        self,
        alert_id: UUID,
        status: str,
    ) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(PostMonitorAlertModel)
            .where(PostMonitorAlertModel.alert_id == alert_id)
            .limit(1)
        )
        alert = result.scalar_one_or_none()
        if alert is None:
            return None
        now = datetime.now(UTC)
        alert.status = status
        if status == "acknowledged":
            alert.acknowledged_at = now
        if status in {"resolved", "dismissed"}:
            alert.acknowledged_at = alert.acknowledged_at or now
            alert.resolved_at = now
        await self._session.commit()
        return _alert_dict(alert)

    async def _existing_receipt(
        self,
        bot_id: UUID,
        event_id: UUID,
        payload_hash: str,
    ) -> PostMonitorEventReceipt | None:
        result = await self._session.execute(
            select(PostMonitorEventModel).where(
                PostMonitorEventModel.bot_id == bot_id,
                PostMonitorEventModel.event_id == event_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            return None
        if existing.payload_hash != payload_hash:
            raise PostMonitorEventConflictError(
                "event_id was already stored with different content"
            )
        return PostMonitorEventReceipt(
            event_id=event_id,
            stored_at=existing.received_at,
            duplicate=True,
        )

    async def _commit_event(
        self,
        bot_id: UUID,
        event_id: UUID,
        payload_hash: str,
        stored_at: datetime,
    ) -> PostMonitorEventReceipt:
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            existing = await self._existing_receipt(bot_id, event_id, payload_hash)
            if existing is not None:
                return existing
            raise PostMonitorProjectionConflictError(
                "run_id or alert_id already exists with a different event"
            ) from None
        return PostMonitorEventReceipt(
            event_id=event_id,
            stored_at=stored_at,
            duplicate=False,
        )


def _serialized_event(
    message: PostMonitorRunResultMessage | PostMonitorThresholdAlertMessage,
) -> tuple[dict[str, Any], str]:
    raw = message.model_dump(mode="json")
    canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return raw, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bot_dict(model: PostMonitorBotModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "bot_key": model.bot_key,
        "name": model.name,
        "version": model.version,
        "environment": model.environment,
        "metadata": dict(model.metadata_json),
        "enabled": model.enabled,
        "reported_status": model.reported_status,
        "current_jobs": model.current_jobs,
        "outbox_pending": model.outbox_pending,
        "last_seen_at": model.last_seen_at,
    }


def _run_dict(model: PostMonitorRunModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "bot_id": model.bot_id,
        "run_id": model.run_id,
        "event_id": model.source_event_id,
        "status": model.status,
        "target": {
            "external_id": model.target_external_id,
            "url": model.target_url,
            "title": model.target_title,
        },
        "started_at": model.started_at,
        "finished_at": model.finished_at,
        "duration_ms": model.duration_ms,
        "summary": model.summary,
        "metrics": dict(model.metrics),
        "result": dict(model.result),
        "error": dict(model.error) if model.error is not None else None,
        "artifacts": list(model.artifacts),
        "created_at": model.created_at,
    }


def _alert_dict(model: PostMonitorAlertModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "bot_id": model.bot_id,
        "alert_id": model.alert_id,
        "event_id": model.source_event_id,
        "run_id": model.run_id,
        "severity": model.severity,
        "metric": model.metric,
        "observed_value": model.observed_value,
        "operator": model.operator,
        "threshold": model.threshold,
        "unit": model.unit,
        "message": model.message,
        "rule": dict(model.rule_snapshot),
        "target": dict(model.target),
        "details": dict(model.details),
        "status": model.status,
        "occurred_at": model.occurred_at,
        "acknowledged_at": model.acknowledged_at,
        "resolved_at": model.resolved_at,
        "created_at": model.created_at,
    }
