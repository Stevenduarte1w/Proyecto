from __future__ import annotations

import base64
import os
import re
from pathlib import Path

from openai import OpenAI
from PIL import Image

from app.utils.file_downloader import download_and_resize


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^\w-]+", "-", value, flags=re.UNICODE).strip("-_")
    return (stem[:80] or "wordpress-post").lower()


def resolve_image(*, drive_url: str | None, image_prompt: str | None, title: str,
                  output_dir: str, api_key: str | None = None,
                  image_model: str | None = None) -> tuple[Path, Path]:
    """Use the supplied Drive artwork, or create an original image with OpenAI."""
    if drive_url and drive_url.strip():
        return download_and_resize(drive_url.strip(), output_dir, title)
    prompt = (image_prompt or "").strip() or (
        f"Create an original, polished editorial illustration for a blog post about {title}. "
        "No text, letters, logos, watermark, or recognizable copyrighted character."
    )
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError("Para generar una imagen se requiere OPENAI_API_KEY o una URL de imagen de Drive.")
    client = OpenAI(api_key=key)
    result = client.images.generate(
        model=image_model or os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2"),
        prompt=prompt,
        size="1024x1024",
    )
    encoded = getattr(result.data[0], "b64_json", None)
    if not encoded:
        raise RuntimeError("OpenAI no devolvió la imagen en formato base64.")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(title)
    original = directory / f"{stem}-original.png"
    resized = directory / f"{stem}.webp"
    original.write_bytes(base64.b64decode(encoded))
    with Image.open(original) as image:
        image = image.convert("RGB")
        image.thumbnail((1400, 800), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (700, 400), "white")
        image.thumbnail((700, 400), Image.Resampling.LANCZOS)
        canvas.paste(image, ((700 - image.width) // 2, (400 - image.height) // 2))
        canvas.save(resized, format="WEBP", quality=88, method=6)
    return resized, original
