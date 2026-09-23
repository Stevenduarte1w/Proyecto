from __future__ import annotations

from html import escape
from urllib.parse import urlparse


def _anchor(label: str, url: str) -> str:
    label, url = label.strip(), url.strip()
    if not label or not url:
        return ""
    if urlparse(url).scheme not in {"http", "https"}:
        raise ValueError(f"URL inválida para enlace editorial: {url}")
    return f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(label)}</a>'


def build_links(labels: str | None, urls: str | None, *, strict: bool = True) -> list[str]:
    names = [part.strip() for part in (labels or "").split(",") if part.strip()]
    links = [part.strip() for part in (urls or "").split(",") if part.strip()]
    if strict and len(names) != len(links):
        raise ValueError(f"Enlaces desparejados: {len(names)} textos y {len(links)} URLs")
    return [_anchor(name, url) for name, url in zip(names, links)]


def assemble(body: str, *, external_link: str = "", media: dict | None = None,
             alt_text: str = "", city_links: list[str] | str = "") -> str:
    """Keep the legacy editor's content → external link → image → city links order."""
    blocks = [body.strip()]
    if external_link.strip():
        blocks.append(f"<p>{external_link.strip()}</p>")
    if media and media.get("url"):
        url = escape(str(media["url"]), quote=True)
        alt = escape(alt_text, quote=True)
        blocks.append(
            f'<figure class="wp-block-image size-full"><img src="{url}" alt="{alt}" class="wp-image-{int(media["id"])}" /></figure>'
        )
    if isinstance(city_links, list):
        city_block = ", ".join(link for link in city_links if link)
    else:
        city_block = city_links.strip()
    if city_block:
        blocks.append(f"<p>{city_block}</p>")
    return "\n\n".join(block for block in blocks if block)
