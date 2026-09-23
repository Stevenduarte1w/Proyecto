from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clients.wordpress_client import PostRef, WordPressClient
from app.core.content_assembler import assemble, build_links
from app.models.campaign import Campaign
from app.models.execution import Execution
from app.models.optimize import OptimizedPost
from app.models.wordpress_site import WordPressSite

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishRequest:
    campaign_id: int
    title: str
    content: str
    seo_title: str = ""
    slug: str = ""
    meta_description: str = ""
    keyphrase: str = ""
    categories: str = ""
    hashtags: str = ""
    image_path: str | None = None
    external_link: str = ""
    citys: str = ""
    citys_urls: str = ""
    create_category: bool = False
    external_id: str | None = None


class PublishingService:
    def __init__(self, db: Session, *, image_dir: str = "app/static/images"):
        self.db = db
        self.image_dir = image_dir

    def _site(self, campaign_id: int) -> WordPressSite:
        campaign = self.db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign or not campaign.is_active:
            raise ValueError(f"Campaña {campaign_id} inexistente o inactiva")
        site = self.db.query(WordPressSite).filter(
            WordPressSite.id == campaign.wordpress_site_id,
            WordPressSite.is_active.is_(True),
        ).first()
        if not site:
            raise ValueError(f"La campaña {campaign_id} no tiene un sitio WordPress activo")
        return site

    @contextmanager
    def _site_lock(self, site_id: int):
        """A PostgreSQL advisory lock serializes writes to the same WP site across workers."""
        connection = self.db.get_bind().connect()
        locked = False
        try:
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                locked = bool(connection.execute(
                    text("SELECT pg_try_advisory_lock(84217, :site_id)"), {"site_id": site_id}
                ).scalar())
                if locked:
                    break
                time.sleep(0.25)
            if not locked:
                raise TimeoutError(f"Timed out waiting for WordPress site lock {site_id}")
            yield
        finally:
            if locked:
                connection.execute(text("SELECT pg_advisory_unlock(84217, :site_id)"), {"site_id": site_id})
            connection.close()

    @staticmethod
    def _term_ids(client: WordPressClient, taxonomy: str, raw: str, *, create: bool) -> list[int]:
        names = [raw.strip()] if raw and raw.strip() else []
        ids: list[int] = []
        for name in names:
            try:
                term_id = client.resolve_term(taxonomy, name, create=create)
                if term_id is None:
                    logger.warning("No se encontró %s %r; se publicará sin ese término", taxonomy, name)
                    continue
                ids.append(term_id)
            except Exception:
                if create:
                    raise
                logger.exception("No se pudo resolver %s %r; se continuará sin ese término", taxonomy, name)
        return ids

    def publish(self, request: PublishRequest) -> dict[str, Any]:
        site = self._site(request.campaign_id)
        with self._site_lock(site.id):
            return self._publish_locked(request, site)

    def _publish_locked(self, request: PublishRequest, site: WordPressSite) -> dict[str, Any]:
        with WordPressClient(site) as wp:
            wp.preflight(site.yoast_enabled)
            execution = (self.db.query(Execution).filter(Execution.external_id == request.external_id).first()
                         if request.external_id else None)
            if execution and execution.result:
                try:
                    partial = json.loads(execution.result)
                    recovered = int(partial["wp_post_id"]) if partial.get("draft_created") else None
                except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                    recovered = None
                if recovered:
                    draft = wp.get_post("posts", recovered)
                    if site.yoast_enabled:
                        wp.update_post("posts", recovered, {"meta": {
                            "_yoast_wpseo_title": request.seo_title,
                            "_yoast_wpseo_metadesc": request.meta_description,
                            "_yoast_wpseo_focuskw": request.keyphrase or request.title,
                        }})
                    published = wp.update_post("posts", recovered, {"status": "publish"})
                    return {"wp_post_id": recovered, "wp_post_url": published.get("link"),
                            "media_id": draft.get("featured_media") or None}
            categories = self._term_ids(wp, "categories", request.categories, create=request.create_category)
            tags = []
            for tag in (request.hashtags or "").split(","):
                term_id = self._term_ids(wp, "tags", tag, create=True)
                tags.extend(term_id)

            media = None
            if request.image_path:
                media = wp.upload_media(request.image_path, Path(request.image_path).stem)
            city_links = build_links(request.citys, request.citys_urls, strict=True)
            content = assemble(request.content, external_link=request.external_link,
                               media=media, alt_text=Path(request.image_path).stem if request.image_path else "",
                               city_links=city_links)
            payload: dict[str, Any] = {
                "title": request.title,
                "content": content,
                "status": "draft",
                "categories": categories,
                "tags": tags,
            }
            if request.slug:
                payload["slug"] = request.slug
            if media:
                payload["featured_media"] = media["id"]
            draft = wp.create_post(payload)
            post_id = int(draft["id"])
            if execution:
                execution.result = json.dumps({"wp_post_id": post_id, "draft_created": True})
                self.db.commit()
            try:
                if site.yoast_enabled:
                    wp.update_post("posts", post_id, {"meta": {
                        "_yoast_wpseo_title": request.seo_title,
                        "_yoast_wpseo_metadesc": request.meta_description,
                        "_yoast_wpseo_focuskw": request.keyphrase or request.title,
                    }})
                published = wp.update_post("posts", post_id, {"status": "publish"})
            except Exception:
                # Leave an incomplete post as a draft so a failure never exposes half-configured content.
                logger.exception("La configuración del borrador %s falló; permanece como borrador", post_id)
                raise
        return {"wp_post_id": post_id, "wp_post_url": published.get("link"),
                "media_id": media["id"] if media else None}

    def optimize(self, optimized_post: OptimizedPost, *, content: str, meta_description: str,
                 image_path: str | None, external_link: str = "", create_category: bool = False,
                 keep_slug: bool = True) -> dict[str, Any]:
        site = self._site(optimized_post.campaign_id)
        with self._site_lock(site.id):
            return self._optimize_locked(optimized_post, site, content=content,
                                         meta_description=meta_description, image_path=image_path,
                                         external_link=external_link, create_category=create_category,
                                         keep_slug=keep_slug)

    def _optimize_locked(self, optimized_post: OptimizedPost, site: WordPressSite, *, content: str,
                         meta_description: str, image_path: str | None, external_link: str = "",
                         create_category: bool = False, keep_slug: bool = True) -> dict[str, Any]:
        with WordPressClient(site) as wp:
            writable_meta = wp.preflight(site.yoast_enabled)
            ref = (PostRef(optimized_post.wp_route or "posts", int(optimized_post.wp_post_id))
                   if optimized_post.wp_post_id else wp.resolve_post_ref(optimized_post.edition_url))
            current = wp.get_post(ref.route, ref.id)
            elementor_builder = (current.get("meta") or {}).get("_elementor_edit_mode") == "builder"
            if elementor_builder and "_elementor_edit_mode" not in writable_meta:
                raise ValueError("El MU-plugin de WordPress no permite escribir _elementor_edit_mode")
            categories = self._term_ids(wp, "categories", optimized_post.categories or "", create=create_category)
            tags: list[int] = []
            for tag in (optimized_post.hashtags or "").split(","):
                tags.extend(self._term_ids(wp, "tags", tag, create=True))
            media = wp.upload_media(image_path, Path(image_path).stem) if image_path else None
            city_links = build_links(optimized_post.citys, optimized_post.citys_urls, strict=True)
            final_content = assemble(content, external_link=external_link, media=media,
                                     alt_text=Path(image_path).stem if image_path else "", city_links=city_links)
            meta = {}
            if site.yoast_enabled:
                meta.update({
                    "_yoast_wpseo_title": optimized_post.seo_title or "",
                    "_yoast_wpseo_metadesc": meta_description,
                    "_yoast_wpseo_focuskw": optimized_post.title,
                })
            if elementor_builder:
                meta["_elementor_edit_mode"] = ""
            snapshot = {key: current.get(key) for key in ("slug", "categories", "tags", "featured_media")}
            title_value = current.get("title")
            content_value = current.get("content")
            snapshot["title"] = title_value.get("raw", "") if isinstance(title_value, dict) else title_value
            snapshot["content"] = content_value.get("raw", "") if isinstance(content_value, dict) else content_value
            current_meta = current.get("meta") or {}
            meta_keys = {"_yoast_wpseo_title", "_yoast_wpseo_metadesc", "_yoast_wpseo_focuskw", "_elementor_edit_mode"}
            snapshot["meta"] = {key: current_meta[key] for key in meta_keys if key in current_meta}
            optimized_post.wp_post_id = ref.id
            optimized_post.wp_route = ref.route
            if not optimized_post.previous_snapshot:
                optimized_post.previous_snapshot = json.dumps(snapshot, ensure_ascii=False)
            optimized_post.attempts = (optimized_post.attempts or 0) + 1
            self.db.commit()
            payload: dict[str, Any] = {
                "title": optimized_post.title,
                "content": final_content,
                "categories": categories,
                "tags": tags,
            }
            if meta:
                payload["meta"] = meta
            if media:
                payload["featured_media"] = media["id"]
            if not keep_slug and optimized_post.slug:
                payload["slug"] = optimized_post.slug
            try:
                updated = wp.update_post(ref.route, ref.id, payload)
            except Exception as exc:
                optimized_post.state = "failed"
                optimized_post.last_error = str(exc)[:4000]
                self.db.commit()
                raise
            optimized_post.status = True
            optimized_post.state = "succeeded"
            optimized_post.last_error = None
            optimized_post.claimed_at = None
            self.db.commit()
        return {"wp_post_id": ref.id, "wp_post_url": updated.get("link"),
                "media_id": media["id"] if media else None}

    def rollback(self, optimized_post: OptimizedPost) -> dict[str, Any]:
        if not optimized_post.wp_post_id or not optimized_post.wp_route or not optimized_post.previous_snapshot:
            raise ValueError("No hay una instantánea disponible para revertir")
        snapshot = json.loads(optimized_post.previous_snapshot)
        site = self._site(optimized_post.campaign_id)
        with self._site_lock(site.id), WordPressClient(site) as wp:
            restored = wp.update_post(optimized_post.wp_route, optimized_post.wp_post_id, snapshot)
        return {"wp_post_id": optimized_post.wp_post_id, "wp_post_url": restored.get("link"), "rolled_back": True}
