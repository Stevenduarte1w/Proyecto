"""Compatibility adapter for optimization through WordPress REST."""

from typing import Any

from sqlalchemy.orm import Session

from app.core.publishing_service import PublishingService
from app.models.optimize import OptimizedPost


class OptimizePostController:
    def __init__(self, db: Session):
        self.db = db
        self.publisher = PublishingService(db)

    def optimize_post(
        self,
        campaign_id: int,
        post_data: OptimizedPost,
        meta_description: str,
        content: str,
        image_path: str,
        external_link: str,
        edit_link: str,
        *,
        create_category: bool = False,
        keep_slug: bool = True,
    ) -> dict[str, Any]:
        # Keep the legacy method signature while making the database record the source
        # of truth for the target and campaign.
        post_data.campaign_id = campaign_id
        if edit_link and not post_data.edition_url:
            post_data.edition_url = edit_link
        return self.publisher.optimize(
            post_data,
            content=content,
            meta_description=meta_description,
            image_path=image_path,
            external_link=external_link or "",
            create_category=create_category,
            keep_slug=keep_slug,
        )
