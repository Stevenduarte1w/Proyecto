from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities import (
    Bot,
    Execution,
    ExecutionCheckpoint,
    ExecutionCheckpointStatus,
    ExecutionEvent,
    ExecutionStatus,
    Flow,
    FlowStep,
)
from orchestrator.infrastructure.postgres.models import (
    BotModel,
    ExecutionCheckpointModel,
    ExecutionEventModel,
    ExecutionModel,
    FlowModel,
    FlowStepModel,
)


class SqlAlchemyBotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, bot: Bot) -> Bot:
        model = BotModel(
            id=bot.id,
            bot_key=bot.bot_key,
            name=bot.name,
            bot_type=bot.bot_type,
            base_url=bot.base_url,
            capabilities=bot.capabilities,
            version=bot.version,
            max_concurrency=bot.max_concurrency,
            metadata_json=bot.metadata,
            enabled=bot.enabled,
            last_seen_at=bot.last_seen_at,
        )
        await self._session.merge(model)
        await self._session.commit()
        return bot

    async def get(self, bot_id: UUID) -> Bot | None:
        model = await self._session.get(BotModel, bot_id)
        if model is None:
            return None
        return _bot_from_model(model)

    async def get_by_key(self, bot_key: str) -> Bot | None:
        statement = select(BotModel).where(BotModel.bot_key == bot_key)
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return _bot_from_model(model)

    async def find_enabled_by_capability(self, capability: str) -> Bot | None:
        statement = (
            select(BotModel)
            .where(BotModel.enabled.is_(True))
            .where(BotModel.capabilities.any(capability))
            .limit(1)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return _bot_from_model(model)

    async def list_enabled_by_capability(self, capability: str) -> list[Bot]:
        statement = (
            select(BotModel)
            .where(BotModel.enabled.is_(True))
            .where(BotModel.capabilities.any(capability))
            .order_by(BotModel.last_seen_at.desc().nulls_last())
        )
        result = await self._session.execute(statement)
        return [_bot_from_model(model) for model in result.scalars().all()]


class SqlAlchemyExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, execution: Execution) -> Execution:
        model = ExecutionModel(
            id=execution.id,
            flow_id=execution.flow_id,
            requested_capability=execution.requested_capability,
            status=execution.status,
            bot_id=execution.bot_id,
            step_id=execution.step_id,
            input_document_id=execution.input_document_id,
            output_document_id=execution.output_document_id,
            error_message=execution.error_message,
            internal_state=execution.internal_state,
            started_at=execution.started_at,
            completed_at=execution.completed_at,
            created_at=execution.created_at,
            updated_at=execution.updated_at,
        )
        try:
            await self._session.merge(model)
            await self._session.commit()
            return execution
        except IntegrityError:
            await self._session.rollback()
            if execution.step_id is not None:
                existing = await self._get_by_step_id(execution.step_id)
                if existing is not None:
                    return existing
            raise

    async def get(self, execution_id: UUID) -> Execution | None:
        model = await self._session.get(ExecutionModel, execution_id)
        if model is None:
            return None
        return _execution_from_model(model)

    async def list_dispatchable_for_bot(
        self,
        bot_id: UUID,
        capabilities: list[str],
        limit: int,
    ) -> list[Execution]:
        if not capabilities or limit <= 0:
            return []
        statement = (
            select(ExecutionModel)
            .where(ExecutionModel.requested_capability.in_(capabilities))
            .where(
                (
                    (ExecutionModel.status == ExecutionStatus.PENDING)
                    & (
                        (ExecutionModel.bot_id.is_(None))
                        | (ExecutionModel.bot_id == bot_id)
                    )
                )
                | (
                    (ExecutionModel.status == ExecutionStatus.QUEUED)
                    & (ExecutionModel.bot_id == bot_id)
                )
            )
            .order_by(ExecutionModel.created_at)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [_execution_from_model(model) for model in result.scalars().all()]

    async def list_pending_for_bot(
        self,
        bot_id: UUID,
        capabilities: list[str],
        limit: int,
    ) -> list[Execution]:
        if not capabilities or limit <= 0:
            return []
        statement = (
            select(ExecutionModel)
            .where(ExecutionModel.requested_capability.in_(capabilities))
            .where(ExecutionModel.status == ExecutionStatus.PENDING)
            .where(
                (ExecutionModel.bot_id.is_(None))
                | (ExecutionModel.bot_id == bot_id)
            )
            .order_by(ExecutionModel.created_at)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [_execution_from_model(model) for model in result.scalars().all()]

    async def list_active_for_bot(self, bot_id: UUID) -> list[Execution]:
        statement = (
            select(ExecutionModel)
            .where(ExecutionModel.bot_id == bot_id)
            .where(
                ExecutionModel.status.in_(
                    [
                        ExecutionStatus.QUEUED,
                        ExecutionStatus.RUNNING,
                        ExecutionStatus.CANCELLING,
                    ]
                )
            )
            .order_by(ExecutionModel.created_at)
        )
        result = await self._session.execute(statement)
        return [_execution_from_model(model) for model in result.scalars().all()]

    async def list_by_capabilities(
        self,
        capabilities: Sequence[str],
        *,
        execution_status: ExecutionStatus | None,
        limit: int,
    ) -> tuple[list[Execution], int]:
        if not capabilities or limit <= 0:
            return [], 0
        filters: list[ColumnElement[bool]] = [
            ExecutionModel.requested_capability.in_(list(capabilities))
        ]
        if execution_status is not None:
            filters.append(ExecutionModel.status == execution_status)
        statement = (
            select(ExecutionModel)
            .where(*filters)
            .order_by(ExecutionModel.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        executions = [_execution_from_model(model) for model in result.scalars().all()]
        total = await self._session.scalar(
            select(func.count()).select_from(ExecutionModel).where(*filters)
        )
        return executions, int(total or 0)

    async def _get_by_step_id(self, step_id: UUID) -> Execution | None:
        statement = select(ExecutionModel).where(ExecutionModel.step_id == step_id)
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return _execution_from_model(model) if model is not None else None


def _execution_from_model(model: ExecutionModel) -> Execution:
    return Execution(
        id=model.id,
        flow_id=model.flow_id,
        requested_capability=model.requested_capability,
        status=model.status,
        bot_id=model.bot_id,
        step_id=model.step_id,
        input_document_id=model.input_document_id,
        output_document_id=model.output_document_id,
        error_message=model.error_message,
        internal_state=model.internal_state,
        started_at=model.started_at,
        completed_at=model.completed_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyExecutionCheckpointRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        checkpoint: ExecutionCheckpoint,
    ) -> tuple[ExecutionCheckpoint, bool]:
        statement = (
            insert(ExecutionCheckpointModel)
            .values(
                id=checkpoint.id,
                flow_id=checkpoint.flow_id,
                execution_id=checkpoint.execution_id,
                checkpoint=checkpoint.checkpoint,
                status=checkpoint.status.value,
                mongo_document_id=checkpoint.mongo_document_id,
                error_message=checkpoint.error_message,
                created_at=checkpoint.created_at,
                processed_at=checkpoint.processed_at,
            )
            .on_conflict_do_nothing(constraint="uq_execution_checkpoints_execution_checkpoint")
            .returning(ExecutionCheckpointModel.id)
        )
        result = await self._session.execute(statement)
        created = result.scalar_one_or_none() is not None
        await self._session.commit()
        if created:
            return checkpoint, True
        existing = await self.get(checkpoint.execution_id, checkpoint.checkpoint)
        if existing is None:
            raise RuntimeError("Checkpoint conflict could not be resolved")
        return existing, False

    async def save(self, checkpoint: ExecutionCheckpoint) -> ExecutionCheckpoint:
        await self._session.merge(_execution_checkpoint_to_model(checkpoint))
        await self._session.commit()
        return checkpoint

    async def get(
        self,
        execution_id: UUID,
        checkpoint: str,
    ) -> ExecutionCheckpoint | None:
        statement = select(ExecutionCheckpointModel).where(
            ExecutionCheckpointModel.execution_id == execution_id,
            ExecutionCheckpointModel.checkpoint == checkpoint,
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return _execution_checkpoint_from_model(model) if model is not None else None


class SqlAlchemyExecutionEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: ExecutionEvent) -> tuple[str, int]:
        execution_statement = (
            select(ExecutionModel.id)
            .where(ExecutionModel.id == event.execution_id)
            .with_for_update()
        )
        execution_id = (await self._session.execute(execution_statement)).scalar_one_or_none()
        if execution_id is None:
            await self._session.rollback()
            raise LookupError("Execution not found")

        existing_statement = select(ExecutionEventModel).where(
            ExecutionEventModel.execution_id == event.execution_id,
            ExecutionEventModel.sequence == event.sequence,
        )
        existing = (await self._session.execute(existing_statement)).scalar_one_or_none()
        if existing is not None:
            last_sequence = await self._last_sequence(event.execution_id)
            await self._session.commit()
            return "duplicate", last_sequence + 1

        last_sequence = await self._last_sequence(event.execution_id)
        expected_sequence = last_sequence + 1
        if event.sequence != expected_sequence:
            await self._session.commit()
            return "gap", expected_sequence

        self._session.add(
            ExecutionEventModel(
                id=event.id,
                event_id=event.event_id,
                execution_id=event.execution_id,
                sequence=event.sequence,
                event_type=event.event_type,
                stage=event.stage,
                summary=event.summary,
                payload=event.payload,
                created_at=event.created_at,
            )
        )
        await self._session.commit()
        return "stored", expected_sequence + 1

    async def list_by_execution(
        self,
        execution_id: UUID,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> list[ExecutionEvent]:
        statement = (
            select(ExecutionEventModel)
            .where(ExecutionEventModel.execution_id == execution_id)
            .where(ExecutionEventModel.sequence > after_sequence)
            .order_by(ExecutionEventModel.sequence)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [_execution_event_from_model(model) for model in result.scalars().all()]

    async def _last_sequence(self, execution_id: UUID) -> int:
        statement = select(func.max(ExecutionEventModel.sequence)).where(
            ExecutionEventModel.execution_id == execution_id
        )
        value = (await self._session.execute(statement)).scalar_one()
        return int(value or 0)


class SqlAlchemyFlowRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, flow: Flow) -> Flow:
        model = FlowModel(
            id=flow.id,
            flow_type=flow.flow_type,
            page_url=flow.page_url,
            campaign=flow.campaign,
            commercial_objective=flow.commercial_objective,
            status=flow.status,
            current_step=flow.current_step,
            initial_document_id=flow.initial_document_id,
            correlation_id=flow.correlation_id,
            created_at=flow.created_at,
            updated_at=flow.updated_at,
        )
        await self._session.merge(model)
        await self._session.commit()
        return flow

    async def get(self, flow_id: UUID) -> Flow | None:
        model = await self._session.get(FlowModel, flow_id)
        if model is None:
            return None
        return Flow(
            id=model.id,
            flow_type=model.flow_type,
            page_url=model.page_url,
            campaign=model.campaign,
            commercial_objective=model.commercial_objective,
            status=model.status,
            current_step=model.current_step,
            initial_document_id=model.initial_document_id,
            correlation_id=model.correlation_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class SqlAlchemyFlowStepRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, step: FlowStep) -> FlowStep:
        model = _flow_step_to_model(step)
        await self._session.merge(model)
        await self._session.commit()
        return step

    async def save_many(self, steps: list[FlowStep]) -> list[FlowStep]:
        for step in steps:
            await self._session.merge(_flow_step_to_model(step))
        await self._session.commit()
        return steps

    async def get(self, step_id: UUID) -> FlowStep | None:
        model = await self._session.get(FlowStepModel, step_id)
        if model is None:
            return None
        return _flow_step_from_model(model)

    async def list_by_flow(self, flow_id: UUID) -> list[FlowStep]:
        statement = (
            select(FlowStepModel)
            .where(FlowStepModel.flow_id == flow_id)
            .order_by(FlowStepModel.position)
        )
        result = await self._session.execute(statement)
        return [_flow_step_from_model(model) for model in result.scalars().all()]


def _bot_from_model(model: BotModel) -> Bot:
    return Bot(
        id=model.id,
        bot_key=model.bot_key,
        name=model.name,
        bot_type=model.bot_type,
        base_url=model.base_url,
        capabilities=list(model.capabilities),
        version=model.version,
        max_concurrency=model.max_concurrency,
        metadata=dict(model.metadata_json),
        enabled=model.enabled,
        last_seen_at=model.last_seen_at,
    )


def _flow_step_to_model(step: FlowStep) -> FlowStepModel:
    return FlowStepModel(
        id=step.id,
        flow_id=step.flow_id,
        step_name=step.step_name,
        position=step.position,
        status=step.status,
        requested_capability=step.requested_capability,
        input_document_id=step.input_document_id,
        output_document_id=step.output_document_id,
        execution_id=step.execution_id,
        error_message=step.error_message,
        created_at=step.created_at,
        updated_at=step.updated_at,
        started_at=step.started_at,
        completed_at=step.completed_at,
    )


def _flow_step_from_model(model: FlowStepModel) -> FlowStep:
    return FlowStep(
        id=model.id,
        flow_id=model.flow_id,
        step_name=model.step_name,
        position=model.position,
        status=model.status,
        requested_capability=model.requested_capability,
        input_document_id=model.input_document_id,
        output_document_id=model.output_document_id,
        execution_id=model.execution_id,
        error_message=model.error_message,
        created_at=model.created_at,
        updated_at=model.updated_at,
        started_at=model.started_at,
        completed_at=model.completed_at,
    )


def _execution_checkpoint_to_model(
    checkpoint: ExecutionCheckpoint,
) -> ExecutionCheckpointModel:
    return ExecutionCheckpointModel(
        id=checkpoint.id,
        flow_id=checkpoint.flow_id,
        execution_id=checkpoint.execution_id,
        checkpoint=checkpoint.checkpoint,
        status=checkpoint.status.value,
        mongo_document_id=checkpoint.mongo_document_id,
        error_message=checkpoint.error_message,
        created_at=checkpoint.created_at,
        processed_at=checkpoint.processed_at,
    )


def _execution_checkpoint_from_model(
    model: ExecutionCheckpointModel,
) -> ExecutionCheckpoint:
    return ExecutionCheckpoint(
        id=model.id,
        flow_id=model.flow_id,
        execution_id=model.execution_id,
        checkpoint=model.checkpoint,
        status=ExecutionCheckpointStatus(model.status),
        mongo_document_id=model.mongo_document_id,
        error_message=model.error_message,
        created_at=model.created_at,
        processed_at=model.processed_at,
    )


def _execution_event_from_model(model: ExecutionEventModel) -> ExecutionEvent:
    return ExecutionEvent(
        id=model.id,
        event_id=model.event_id,
        execution_id=model.execution_id,
        sequence=model.sequence,
        event_type=model.event_type,
        stage=model.stage,
        summary=model.summary,
        payload=model.payload,
        created_at=model.created_at,
    )
