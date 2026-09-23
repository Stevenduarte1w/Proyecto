from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.application.post_bot import PostBotService
from orchestrator.application.post_monitor import PostMonitorService
from orchestrator.application.seo_management import SeoManagementService
from orchestrator.application.use_cases.advance_workflow import AdvanceWorkflow
from orchestrator.application.use_cases.cancel_execution import CancelExecution
from orchestrator.application.use_cases.create_standalone_instagram import (
    CreateStandaloneInstagram,
)
from orchestrator.application.use_cases.create_standalone_pagespeed import CreateStandalonePageSpeed
from orchestrator.application.use_cases.dispatch_execution import DispatchExecution
from orchestrator.application.use_cases.execution_documents import (
    GetExecutionInput,
    SubmitExecutionResult,
)
from orchestrator.application.use_cases.instagram_executions import (
    GetInstagramExecutionResult,
    ListInstagramExecutions,
)
from orchestrator.application.use_cases.page_executions import PageExecutionService
from orchestrator.application.use_cases.register_bot import RegisterBot
from orchestrator.application.use_cases.submit_flow import SubmitFlow
from orchestrator.core.config import get_settings
from orchestrator.infrastructure.bots.post_bot_ws_manager import post_bot_ws_manager
from orchestrator.infrastructure.bots.ws_manager import bot_ws_manager
from orchestrator.infrastructure.mongo.page_executions import MongoPageExecutionRepository
from orchestrator.infrastructure.mongo.repositories import MongoFlowDocumentRepository
from orchestrator.infrastructure.postgres.post_bot import SqlAlchemyPostBotRepository
from orchestrator.infrastructure.postgres.post_monitor import (
    SqlAlchemyPostMonitorRepository,
)
from orchestrator.infrastructure.postgres.repositories import (
    SqlAlchemyBotRepository,
    SqlAlchemyExecutionEventRepository,
    SqlAlchemyExecutionRepository,
    SqlAlchemyFlowRepository,
    SqlAlchemyFlowStepRepository,
)
from orchestrator.infrastructure.postgres.session import get_session
from orchestrator.infrastructure.redis.page_logs import RedisPageExecutionLogRepository
from orchestrator.infrastructure.redis.presence import RedisBotPresenceRepository
from orchestrator.infrastructure.seo_agent.management import (
    SqlAlchemySeoAgentManagementRepository,
)
from orchestrator.infrastructure.seo_agent.rankings import (
    BrightLocalRankClient,
    SerperRankClient,
)
from orchestrator.infrastructure.seo_agent.repositories import (
    SqlAlchemySourcePageExecutionRepository,
)


async def db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


def post_monitor_service(
    session: AsyncSession = Depends(db_session),
) -> PostMonitorService:
    settings = get_settings()
    return PostMonitorService(
        repository=SqlAlchemyPostMonitorRepository(session),
        presence_ttl_seconds=settings.post_monitor_presence_ttl_seconds,
    )


def post_bot_service(
    session: AsyncSession = Depends(db_session),
) -> PostBotService:
    settings = get_settings()
    return PostBotService(
        repository=SqlAlchemyPostBotRepository(session),
        command_gateway=post_bot_ws_manager,
        presence_ttl_seconds=settings.post_bot_presence_ttl_seconds,
    )


def register_bot_use_case(
    session: AsyncSession = Depends(db_session),
) -> RegisterBot:
    return RegisterBot(bot_repository=SqlAlchemyBotRepository(session))


def submit_flow_use_case(
    session: AsyncSession = Depends(db_session),
) -> SubmitFlow:
    return SubmitFlow(
        flow_document_repository=MongoFlowDocumentRepository(),
        flow_repository=SqlAlchemyFlowRepository(session),
        flow_step_repository=SqlAlchemyFlowStepRepository(session),
        execution_repository=SqlAlchemyExecutionRepository(session),
        dispatcher=_build_dispatcher(session),
    )


def dispatch_execution_use_case(
    session: AsyncSession = Depends(db_session),
) -> DispatchExecution:
    return _build_dispatcher(session)


def cancel_execution_use_case(
    session: AsyncSession = Depends(db_session),
) -> CancelExecution:
    return CancelExecution(
        execution_repository=SqlAlchemyExecutionRepository(session),
        command_gateway=bot_ws_manager,
    )


def execution_event_repository(
    session: AsyncSession = Depends(db_session),
) -> SqlAlchemyExecutionEventRepository:
    return SqlAlchemyExecutionEventRepository(session)


def create_standalone_pagespeed_use_case(
    session: AsyncSession = Depends(db_session),
) -> CreateStandalonePageSpeed:
    return CreateStandalonePageSpeed(
        execution_repository=SqlAlchemyExecutionRepository(session),
        flow_document_repository=MongoFlowDocumentRepository(),
        dispatcher=_build_dispatcher(session),
    )


def create_standalone_instagram_use_case(
    session: AsyncSession = Depends(db_session),
) -> CreateStandaloneInstagram:
    return CreateStandaloneInstagram(
        execution_repository=SqlAlchemyExecutionRepository(session),
        flow_document_repository=MongoFlowDocumentRepository(),
        dispatcher=_build_dispatcher(session),
    )


def list_instagram_executions_use_case(
    session: AsyncSession = Depends(db_session),
) -> ListInstagramExecutions:
    return ListInstagramExecutions(execution_repository=SqlAlchemyExecutionRepository(session))


def get_instagram_execution_result_use_case(
    session: AsyncSession = Depends(db_session),
) -> GetInstagramExecutionResult:
    return GetInstagramExecutionResult(
        execution_repository=SqlAlchemyExecutionRepository(session),
        flow_document_repository=MongoFlowDocumentRepository(),
    )


def _build_dispatcher(session: AsyncSession) -> DispatchExecution:
    return DispatchExecution(
        execution_repository=SqlAlchemyExecutionRepository(session),
        bot_repository=SqlAlchemyBotRepository(session),
        flow_step_repository=SqlAlchemyFlowStepRepository(session),
        presence_repository=RedisBotPresenceRepository(),
        command_gateway=bot_ws_manager,
        flow_document_repository=MongoFlowDocumentRepository(),
    )


def get_execution_input_use_case(
    session: AsyncSession = Depends(db_session),
) -> GetExecutionInput:
    return GetExecutionInput(
        execution_repository=SqlAlchemyExecutionRepository(session),
        flow_document_repository=MongoFlowDocumentRepository(),
    )


def submit_execution_result_use_case(
    session: AsyncSession = Depends(db_session),
) -> SubmitExecutionResult:
    dispatcher = _build_dispatcher(session)
    workflow_engine = AdvanceWorkflow(
        flow_repository=SqlAlchemyFlowRepository(session),
        flow_step_repository=SqlAlchemyFlowStepRepository(session),
        execution_repository=SqlAlchemyExecutionRepository(session),
        flow_document_repository=MongoFlowDocumentRepository(),
        dispatcher=dispatcher,
    )
    return SubmitExecutionResult(
        execution_repository=SqlAlchemyExecutionRepository(session),
        flow_step_repository=SqlAlchemyFlowStepRepository(session),
        flow_document_repository=MongoFlowDocumentRepository(),
        workflow_engine=workflow_engine,
        seo_management_repository=SqlAlchemySeoAgentManagementRepository(),
        page_execution_service=page_execution_service(),
    )


def advance_workflow_use_case(
    session: AsyncSession = Depends(db_session),
) -> AdvanceWorkflow:
    return AdvanceWorkflow(
        flow_repository=SqlAlchemyFlowRepository(session),
        flow_step_repository=SqlAlchemyFlowStepRepository(session),
        execution_repository=SqlAlchemyExecutionRepository(session),
        flow_document_repository=MongoFlowDocumentRepository(),
        dispatcher=_build_dispatcher(session),
    )


def page_execution_service() -> PageExecutionService:
    settings = get_settings()
    return PageExecutionService(
        source_repository=SqlAlchemySourcePageExecutionRepository(),
        document_repository=MongoPageExecutionRepository(),
        log_repository=RedisPageExecutionLogRepository(),
        log_ttl_seconds=settings.page_execution_log_ttl_seconds,
    )


def seo_management_service(
    session: AsyncSession = Depends(db_session),
) -> SeoManagementService:
    settings = get_settings()
    dispatcher = _build_dispatcher(session)
    rank_provider = (
        BrightLocalRankClient(
            api_key=settings.brightlocal_api_key,
            base_url=settings.brightlocal_api_base_url,
            num_results=settings.brightlocal_rank_num_results,
            timeout_seconds=settings.brightlocal_rank_timeout_seconds,
            poll_interval_seconds=settings.brightlocal_rank_poll_interval_seconds,
        )
        if settings.rank_provider.strip().lower() == "brightlocal"
        else SerperRankClient(
            api_key=settings.serper_api_key,
            base_url=settings.serper_api_base_url,
            num_results=settings.serper_rank_num_results,
            timeout_seconds=settings.serper_request_timeout_seconds,
        )
    )
    return SeoManagementService(
        repository=SqlAlchemySeoAgentManagementRepository(),
        page_execution_service=page_execution_service(),
        submit_flow=SubmitFlow(
            flow_document_repository=MongoFlowDocumentRepository(),
            flow_repository=SqlAlchemyFlowRepository(session),
            flow_step_repository=SqlAlchemyFlowStepRepository(session),
            execution_repository=SqlAlchemyExecutionRepository(session),
            dispatcher=dispatcher,
        ),
        rank_position_provider=rank_provider,
        dispatcher=dispatcher,
    )
