from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from bson import ObjectId

from orchestrator.infrastructure.mongo.client import get_mongo_database


class MongoFlowPayloadRepository:
    collection_name = "seo_flow_payloads"

    async def store(
        self,
        flow_type: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> str:
        document = {
            "flow_id": None,
            "step_name": "initial_request",
            "document_type": flow_type,
            "flow_type": flow_type,
            "payload": payload,
            "correlation_id": correlation_id,
            "created_at": datetime.now(UTC),
        }
        result = await get_mongo_database()[self.collection_name].insert_one(document)
        return str(result.inserted_id)

    async def get(self, flow_id: str) -> dict[str, Any] | None:
        document = await get_mongo_database()[self.collection_name].find_one({"_id": ObjectId(flow_id)})
        if document is None:
            return None
        document["_id"] = str(document["_id"])
        return document


class MongoFlowDocumentRepository:
    collection_name = "seo_flow_documents"

    async def store_document(
        self,
        flow_id: str,
        step_name: str,
        document_type: str,
        payload: Any,
        execution_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> str:
        document = {
            "flow_id": flow_id,
            "step_name": step_name,
            "document_type": document_type,
            "payload": payload,
            "execution_id": str(execution_id) if execution_id else None,
            "correlation_id": correlation_id,
            "created_at": datetime.now(UTC),
        }
        result = await get_mongo_database()[self.collection_name].insert_one(document)
        return str(result.inserted_id)

    async def get_document(self, document_id: str) -> dict[str, Any] | None:
        document = await get_mongo_database()[self.collection_name].find_one(
            {"_id": ObjectId(document_id)}
        )
        if document is None:
            return None
        document["_id"] = str(document["_id"])
        return document
