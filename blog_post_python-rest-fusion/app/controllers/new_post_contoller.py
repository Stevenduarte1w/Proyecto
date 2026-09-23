"""Compatibility adapter for creating a post through the shared REST core."""

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.publishing_service import PublishRequest, PublishingService
from app.models.post import Post


class NewPostController:
    def __init__(self, db: Session):
        self.db = db
        self.publisher = PublishingService(db)

    def create_new_post(
        self,
        campaign_id: int,
        post_data: Post,
        meta_description: str,
        content: str,
        image_path: str,
        external_link: str,
        *,
        create_category: bool = False,
        external_id: str | None = None,
    ) -> dict[str, Any]:
        return self.publisher.publish(PublishRequest(
            campaign_id=campaign_id,
            title=post_data.title,
            content=content,
            seo_title=post_data.seo_title or "",
            slug=getattr(post_data, "slug", "") or "",
            meta_description=meta_description,
            keyphrase=post_data.title,
            categories=post_data.categories or "",
            hashtags=post_data.hashtags or "",
            image_path=str(image_path) if image_path else None,
            external_link=external_link or "",
            citys=post_data.citys or "",
            citys_urls=post_data.citys_urls or "",
            create_category=create_category,
            external_id=external_id,
        ))
