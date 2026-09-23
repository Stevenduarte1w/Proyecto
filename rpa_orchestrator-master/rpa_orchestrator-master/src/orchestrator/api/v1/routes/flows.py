from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.v1.dependencies import (
    advance_workflow_use_case,
    db_session,
    submit_flow_use_case,
)
from orchestrator.application.dtos import (
    FlowResponse,
    FlowStepResponse,
    FlowSubmitRequest,
    FlowSubmitResponse,
    WorkflowAdvanceResponse,
)
from orchestrator.application.use_cases.advance_workflow import AdvanceWorkflow
from orchestrator.application.use_cases.submit_flow import SubmitFlow
from orchestrator.infrastructure.postgres.repositories import (
    SqlAlchemyFlowRepository,
    SqlAlchemyFlowStepRepository,
)

router = APIRouter()


@router.post("", response_model=FlowSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_flow(
    payload: FlowSubmitRequest,
    use_case: SubmitFlow = Depends(submit_flow_use_case),
) -> FlowSubmitResponse:
    return await use_case.execute(payload)


@router.get("/{flow_id}", response_model=FlowResponse)
async def get_flow(
    flow_id: UUID,
    session: AsyncSession = Depends(db_session),
) -> FlowResponse:
    flow = await SqlAlchemyFlowRepository(session).get(flow_id)
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flow not found")
    return FlowResponse(**asdict(flow))


@router.get("/{flow_id}/steps", response_model=list[FlowStepResponse])
async def list_flow_steps(
    flow_id: UUID,
    session: AsyncSession = Depends(db_session),
) -> list[FlowStepResponse]:
    flow = await SqlAlchemyFlowRepository(session).get(flow_id)
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flow not found")

    steps = await SqlAlchemyFlowStepRepository(session).list_by_flow(flow_id)
    return [FlowStepResponse(**asdict(step)) for step in steps]


@router.post("/{flow_id}/advance", response_model=WorkflowAdvanceResponse)
async def advance_flow(
    flow_id: UUID,
    use_case: AdvanceWorkflow = Depends(advance_workflow_use_case),
) -> WorkflowAdvanceResponse:
    result = await use_case.execute(flow_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flow not found")
    return result
