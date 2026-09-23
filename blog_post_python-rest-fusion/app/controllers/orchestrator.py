"""Local AI authoring pipeline; publishing is always delegated to REST core."""

import logging
import os
import uuid

from app.controllers.content_controller import NewPostContent
from app.controllers.new_post_contoller import NewPostController
from app.controllers.optimize_post_controller import OptimizePostController
from app.core.content_assembler import build_links
from app.models.optimize import OptimizedPost
from app.models.post import Post
from app.utils.file_downloader import delete_files
from app.utils.image_resolver import resolve_image

logger = logging.getLogger(__name__)


class PostOrchestrator:
    """Generate original text/images locally, then publish through WordPress REST."""

    def __init__(self, db):
        self.db = db
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.image_dir = os.getenv("IMAGE_OUTPUT_DIR", "app/static/images")
        self.new_post_controller = NewPostController(db)
        self.optimize_post_controller = OptimizePostController(db)

    def _generate(self, post_data, language: str) -> tuple[str, str, str]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY no está configurada para generar contenido.")
        language = (language or "").strip().lower()
        if language not in {"es", "en"}:
            raise ValueError(f"Idioma no soportado: {language or '(vacío)'}")
        generator = NewPostContent(self.api_key, language)
        keyword_links = build_links(post_data.keywords, post_data.keywords_urls, strict=True)
        conclusion_links = build_links(post_data.conclusions, post_data.conclusions_urls, strict=True)
        external_links = build_links(post_data.external, post_data.external_url, strict=True)

        if language == "en":
            body = generator.english_introduction(post_data.title, keyword_links)
            raw = generator.english_content(post_data.title)
            body += generator.humanize_content(raw, post_data.title)
            body = generator.humanize_content2(body, post_data.title)
            body += generator.english_conclusion(post_data.title, conclusion_links)
        else:
            body = generator.botanic_introduction(post_data.title, keyword_links)
            body += generator.botanic_content(post_data.title)
            body += generator.botanic_conclusion(post_data.title, conclusion_links)
        description = generator.yoast_description(post_data.title)
        external = external_links[0] if external_links else ""
        return body, description, external

    def _image(self, post_data):
        output_dir = os.path.join(self.image_dir, uuid.uuid4().hex)
        return resolve_image(
            drive_url=getattr(post_data, "image", None),
            image_prompt=getattr(post_data, "image_prompt", None),
            title=post_data.title,
            output_dir=output_dir,
            api_key=self.api_key,
            image_model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2"),
        )

    def create_new_post(self, campaign_id: int, post_data: Post, language: str, *, external_id=None,
                        create_category: bool = False):
        body, description, external = self._generate(post_data, language)
        image_path, original_path = self._image(post_data)
        try:
            result = self.new_post_controller.create_new_post(
                campaign_id, post_data, description, body, str(image_path), external,
                create_category=create_category, external_id=external_id,
            )
            return result
        finally:
            delete_files(str(image_path), str(original_path))
            try:
                image_path.parent.rmdir()
            except OSError:
                pass

    def optimize_post(self, campaign_id: int, post_data: OptimizedPost, language: str, *,
                      create_category: bool = False, keep_slug: bool = True):
        body, description, external = self._generate(post_data, language)
        image_path, original_path = self._image(post_data)
        try:
            return self.optimize_post_controller.optimize_post(
                campaign_id, post_data, description, body, str(image_path), external,
                edit_link=post_data.edition_url, create_category=create_category,
                keep_slug=keep_slug,
            )
        finally:
            delete_files(str(image_path), str(original_path))
            try:
                image_path.parent.rmdir()
            except OSError:
                pass
