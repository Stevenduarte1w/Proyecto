from __future__ import annotations

from typing import Any
from uuid import UUID

from orchestrator.domain.entities import Execution, ExecutionStatus
from orchestrator.domain.instagram import INSTAGRAM_CAPABILITIES
from orchestrator.domain.ports import (
    ExecutionListingRepository,
    ExecutionRepository,
    FlowDocumentRepository,
)


class ListInstagramExecutions:
    """Historial de ejecuciones acotado a las capabilities de Instagram.

    El filtro por capability no es opcional: esta vista nunca devuelve
    ejecuciones de paginas, backlinks ni del resto de flujos.
    """

    def __init__(self, execution_repository: ExecutionListingRepository) -> None:
        self._execution_repository = execution_repository

    async def execute(
        self,
        *,
        capability: str | None = None,
        execution_status: ExecutionStatus | None = None,
        limit: int = 50,
    ) -> tuple[list[Execution], int]:
        if capability is not None and capability not in INSTAGRAM_CAPABILITIES:
            raise ValueError("unsupported Instagram capability")
        capabilities = [capability] if capability else sorted(INSTAGRAM_CAPABILITIES)
        return await self._execution_repository.list_by_capabilities(
            capabilities,
            execution_status=execution_status,
            limit=limit,
        )


class GetInstagramExecutionResult:
    """Documento de salida de una ejecucion de Instagram.

    Solo se expone el `payload` del documento: el id de Mongo, la metadata de
    almacenamiento y el sobre interno siguen siendo un detalle del
    orquestador. Las ejecuciones que no son de Instagram se tratan como
    inexistentes.
    """

    def __init__(
        self,
        execution_repository: ExecutionRepository,
        flow_document_repository: FlowDocumentRepository,
    ) -> None:
        self._execution_repository = execution_repository
        self._flow_document_repository = flow_document_repository

    async def execute(
        self,
        execution_id: UUID,
    ) -> tuple[ExecutionStatus | None, dict[str, Any] | None]:
        execution = await self._execution_repository.get(execution_id)
        if execution is None or execution.requested_capability not in INSTAGRAM_CAPABILITIES:
            return None, None

        if execution.output_document_id is None:
            return execution.status, None

        document = await self._flow_document_repository.get_document(
            execution.output_document_id
        )
        if document is None:
            return execution.status, None

        payload = document.get("payload")
        if not isinstance(payload, dict):
            return execution.status, None

        return execution.status, payload
