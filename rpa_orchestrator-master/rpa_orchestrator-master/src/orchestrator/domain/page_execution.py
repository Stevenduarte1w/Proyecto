from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

REFERENCE_ARTIFACT_FILENAMES: tuple[str, ...] = (
    "auto_local_research.json",
    "resource_city_links_update.json",
    "heading_duplicates_report.json",
    "mixed_widget_duplicate_cleanup.json",
    "support_post_1.json",
    "support_post_2.json",
    "support_post_packages.json",
    "support_posts_local_research.json",
    "external_video_bot_payload.json",
    "featured_image_metadata.json",
    "schema_custom_built.json",
    "saswp_schema_maintenance_payload.json",
    "saswp_schema_maintenance_response.json",
    "final_page_quality_review_initial.json",
    "final_page_quality_corrections_applied.json",
)


@dataclass(frozen=True, slots=True)
class SourcePageExecution:
    queue_execution_id: int
    campaign_page_id: int
    campaign_id: int
    campaign_name: str
    page_slug: str
    page_url: str | None = None
    wp_page_id: int | None = None
    trigger_type: str | None = None
    status: str | None = None
    scheduled_for: date | datetime | None = None
    priority: int | None = None
    attempts: int | None = None
    max_attempts: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    log_path: str | None = None
    source_record: dict[str, Any] = field(default_factory=dict)


def page_execution_log_key(execution: SourcePageExecution) -> str:
    return (
        f"seo:campaign:{execution.campaign_id}:page:{execution.campaign_page_id}:"
        f"execution:{execution.queue_execution_id}:log"
    )


def page_execution_history_log_key(execution: SourcePageExecution) -> str:
    return (
        f"seo:campaign:{execution.campaign_id}:page:{execution.campaign_page_id}:"
        "bot:log"
    )
