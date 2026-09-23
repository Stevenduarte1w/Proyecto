from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from orchestrator.domain.page_execution import SourcePageExecution
from orchestrator.infrastructure.seo_agent.client import get_seo_agent_engine


class SqlAlchemySourcePageExecutionRepository:
    async def get(self, queue_execution_id: int) -> SourcePageExecution | None:
        statement = text(
            """
            SELECT
                q.*,
                cp.campaign_id AS resolved_campaign_id,
                cp.slug AS resolved_page_slug,
                cp.url AS resolved_page_url,
                cp.wp_page_id AS resolved_wp_page_id,
                c.name AS resolved_campaign_name
            FROM page_execution_queue AS q
            JOIN campaign_pages AS cp ON cp.id = q.campaign_page_id
            JOIN campaigns AS c ON c.id = cp.campaign_id
            WHERE q.id = :queue_execution_id
            """
        )
        async with get_seo_agent_engine().connect() as connection:
            result = await connection.execute(
                statement,
                {"queue_execution_id": queue_execution_id},
            )
            row = result.mappings().one_or_none()

        if row is None:
            return None
        return _source_execution_from_row(row)


def _source_execution_from_row(row: RowMapping) -> SourcePageExecution:
    source_record = dict(row)
    return SourcePageExecution(
        queue_execution_id=int(row["id"]),
        campaign_page_id=int(row["campaign_page_id"]),
        campaign_id=int(row["resolved_campaign_id"]),
        campaign_name=str(row["resolved_campaign_name"]),
        page_slug=str(row["resolved_page_slug"]),
        page_url=_optional_str(row.get("resolved_page_url")),
        wp_page_id=_optional_int(row.get("resolved_wp_page_id")),
        trigger_type=_optional_str(row.get("trigger_type")),
        status=_optional_str(row.get("status")),
        scheduled_for=row.get("scheduled_for"),
        priority=_optional_int(row.get("priority")),
        attempts=_optional_int(row.get("attempts")),
        max_attempts=_optional_int(row.get("max_attempts")),
        started_at=row.get("started_at"),
        finished_at=_first_value(row, "finished_at", "completed_at"),
        log_path=_optional_str(_first_value(row, "log_path", "log_file", "log_file_path")),
        source_record=source_record,
    )


def _first_value(row: RowMapping, *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None
