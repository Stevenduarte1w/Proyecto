from typing import Any

from pydantic import BaseModel, Field


class OrchestratorPost(BaseModel):
    campaign_id: int
    title: str
    content: str = Field(min_length=1)
    seo_title: str = ""
    slug: str = ""
    meta_description: str = ""
    keyphrase: str = ""
    categories: str = ""
    hashtags: str = ""
    image: str | None = None
    image_prompt: str | None = None
    external: str = ""
    external_url: str = ""
    external_link: str = ""
    citys: str = ""
    citys_urls: str = ""
    create_category: bool = False
    wp_post_id: int | None = None
    edition_url: str | None = None
    wp_route: str = "posts"
    keep_slug: bool = True
    keep_featured_image: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrchestratorJob(BaseModel):
    id: str | None = None
    job_id: str | None = None
    execution_id: str | None = None
    external_ref: str | None = None
    capability: str = "posts.create"
    campaign_id: int | None = None
    posts: list[OrchestratorPost] = Field(default_factory=list)
    post: OrchestratorPost | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}
