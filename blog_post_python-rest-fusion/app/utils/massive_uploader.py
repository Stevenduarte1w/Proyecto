from __future__ import annotations

from datetime import datetime
from typing import IO

import pandas as pd
from sqlalchemy.orm import Session

from app.models.campaign import Campaign
from app.models.wordpress_site import WordPressSite
from app.schemas.optimize import OptimizedPostCreate
from app.schemas.post import PostCreate
from app.services.optimize import OptimizedPostService
from app.services.post import PostService

NEW_REQUIRED = {
    "id_campaign", "title_post", "title_seo", "keywords", "urls",
    "conclusion_keywords", "conclusion_urls", "city_keywords", "city_urls",
    "external_phrase", "external_url", "slug", "hashtags", "language",
    "categories",
}
OPTIMIZE_REQUIRED = (NEW_REQUIRED - {"title_post", "slug"}) | {"title", "edition_url"}


def _clean(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str):
        return value.replace("\u200b", "").strip()
    return str(value)


def _validate_frame(file: IO, required: set[str]):
    frame = pd.read_excel(file)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("Faltan columnas requeridas: " + ", ".join(missing))
    return frame


def _campaign_error(db: Session, campaign_id: int) -> str | None:
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign or not campaign.is_active:
        return f"La campaña {campaign_id} no existe o está inactiva"
    site = db.query(WordPressSite).filter(WordPressSite.id == campaign.wordpress_site_id).first()
    if not site or not site.is_active:
        return f"La campaña {campaign_id} no tiene sitio WordPress activo"
    return None


def upload_new_posts(file: IO, db: Session):
    try:
        frame = _validate_frame(file, NEW_REQUIRED)
    except Exception as exc:
        return {"created": [], "errors": [{"row": 0, "error": str(exc)}]}
    service = PostService(db)
    results = {"created": [], "errors": []}
    for index, row in frame.iterrows():
        try:
            campaign_id = int(row["id_campaign"])
            issue = _campaign_error(db, campaign_id)
            if issue:
                raise ValueError(issue)
            date_value = pd.to_datetime(row["date"]) if "date" in frame and not pd.isna(row.get("date")) else datetime.now()
            item = PostCreate(
                campaign_id=campaign_id,
                title=_clean(row["title_post"]), seo_title=_clean(row["title_seo"]),
                keywords=_clean(row["keywords"]), keywords_urls=_clean(row["urls"]),
                conclusions=_clean(row["conclusion_keywords"]), conclusions_urls=_clean(row["conclusion_urls"]),
                citys=_clean(row["city_keywords"]), citys_urls=_clean(row["city_urls"]),
                external=_clean(row["external_phrase"]), external_url=_clean(row["external_url"]),
                slug=_clean(row["slug"]), hashtags=_clean(row["hashtags"]),
                language=_clean(row["language"]), image=_clean(row.get("image")),
                image_prompt=_clean(row.get("image_prompt")), categories=_clean(row["categories"]),
                date=date_value,
            )
            results["created"].append(service.create_post(item))
        except Exception as exc:
            db.rollback()
            results["errors"].append({"row": index + 2, "error": str(exc)})
    return results


def upload_optimize_posts(file: IO, db: Session):
    try:
        frame = _validate_frame(file, OPTIMIZE_REQUIRED)
    except Exception as exc:
        return {"created": [], "errors": [{"row": 0, "error": str(exc)}]}
    service = OptimizedPostService(db)
    results = {"created": [], "errors": []}
    for index, row in frame.iterrows():
        try:
            campaign_id = int(row["id_campaign"])
            issue = _campaign_error(db, campaign_id)
            if issue:
                raise ValueError(issue)
            date_value = pd.to_datetime(row["date"]) if "date" in frame and not pd.isna(row.get("date")) else datetime.now()
            item = OptimizedPostCreate(
                campaign_id=campaign_id,
                title=_clean(row["title"]), seo_title=_clean(row["title_seo"]),
                keywords=_clean(row["keywords"]), keywords_urls=_clean(row["urls"]),
                conclusions=_clean(row["conclusion_keywords"]), conclusions_urls=_clean(row["conclusion_urls"]),
                citys=_clean(row["city_keywords"]), citys_urls=_clean(row["city_urls"]),
                external=_clean(row["external_phrase"]), external_url=_clean(row["external_url"]),
                hashtags=_clean(row["hashtags"]), language=_clean(row["language"]),
                image=_clean(row.get("image")), image_prompt=_clean(row.get("image_prompt")),
                categories=_clean(row["categories"]), edition_url=_clean(row["edition_url"]),
                slug=_clean(row.get("slug")), date=date_value,
            )
            results["created"].append(service.create_optimized_post(item))
        except Exception as exc:
            db.rollback()
            results["errors"].append({"row": index + 2, "error": str(exc)})
    return results
