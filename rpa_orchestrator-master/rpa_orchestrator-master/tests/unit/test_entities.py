from __future__ import annotations

from uuid import uuid4

from orchestrator.domain.entities import Execution, ExecutionStatus


def test_execution_state_changes_update_status() -> None:
    execution = Execution(flow_id="flow-1", requested_capability="seo.audit")

    execution.assign_bot(uuid4())
    execution.mark_queued()

    assert execution.status is ExecutionStatus.QUEUED
    assert execution.bot_id is not None

