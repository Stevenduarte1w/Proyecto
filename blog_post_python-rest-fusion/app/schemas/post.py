from datetime import datetime

from pydantic import BaseModel


class PostCreate(BaseModel):
    title: str
    campaign_id: int
    date: datetime
    seo_title: str | None = None
    keywords: str | None = None
    keywords_urls: str | None = None
    conclusions: str | None = None
    conclusions_urls: str | None = None
    citys: str | None = None
    citys_urls: str | None = None
    external: str | None = None
    external_url: str | None = None
    slug: str | None = None
    hashtags: str | None = None
    language: str | None = None
    image: str | None = None
    image_prompt: str | None = None
    categories: str | None = None


class PostUpdate(BaseModel):
    title: str | None = None
    seo_title: str | None = None
    keywords: str | None = None
    keywords_urls: str | None = None
    conclusions: str | None = None
    conclusions_urls: str | None = None
    citys: str | None = None
    citys_urls: str | None = None
    external: str | None = None
    external_url: str | None = None
    slug: str | None = None
    hashtags: str | None = None
    language: str | None = None
    image: str | None = None
    image_prompt: str | None = None
    categories: str | None = None
    date: datetime | None = None
    state: str | None = None


class PostResponse(BaseModel):
    id: int
    title: str
    seo_title: str | None = None
    keywords: str | None = None
    keywords_urls: str | None = None
    conclusions: str | None = None
    conclusions_urls: str | None = None
    citys: str | None = None
    citys_urls: str | None = None
    external: str | None = None
    external_url: str | None = None
    slug: str | None = None
    hashtags: str | None = None
    language: str | None = None
    image: str | None = None
    image_prompt: str | None = None
    categories: str | None = None
    date: datetime
    campaign_id: int
    state: str
    attempts: int = 0
    last_error: str | None = None
    published_at: datetime | None = None
    wp_post_id: int | None = None
    wp_post_url: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
