"""Small, defensive client for the WordPress REST API."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests
from requests.auth import HTTPBasicAuth


@dataclass(frozen=True)
class PostRef:
    route: str
    id: int


class WordPressError(RuntimeError):
    pass


class WordPressClient:
    def __init__(self, site: Any, timeout: int = 45, max_attempts: int = 3):
        self.site = site
        self.base_url = site.url.rstrip("/")
        if urlparse(self.base_url).scheme not in {"http", "https"} or not urlparse(self.base_url).hostname:
            raise WordPressError("La URL del sitio WordPress debe usar http o https")
        credential_ref = site.credential_ref
        password = os.getenv(credential_ref, "") if credential_ref else ""
        if not password:
            raise WordPressError(
                f"Falta la Application Password configurada en {credential_ref or 'credential_ref'}"
            )
        self.timeout = int(os.getenv("WORDPRESS_HTTP_TIMEOUT", timeout))
        self.max_attempts = max(1, int(os.getenv("WORDPRESS_MAX_READ_RETRIES", max_attempts)))
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(site.username, password)
        self.session.headers.update({"Accept": "application/json", "User-Agent": "BlogPostBot/3"})

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "WordPressClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def api(self) -> str:
        return f"{self.base_url}/wp-json/wp/v2"

    def request(self, method: str, endpoint: str, *, retry_read: bool = True, **kwargs: Any) -> requests.Response:
        method = method.upper()
        url = endpoint if endpoint.startswith(("http://", "https://")) else f"{self.api}/{endpoint.lstrip('/')}"
        attempts = self.max_attempts if retry_read and method in {"GET", "HEAD", "OPTIONS"} else 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
                if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
                    wait = response.headers.get("Retry-After")
                    time.sleep(min(float(wait) if wait and wait.isdigit() else 2 ** attempt, 8))
                    continue
                if not response.ok:
                    try:
                        detail = response.json().get("message") or response.text[:500]
                    except ValueError:
                        detail = response.text[:500]
                    raise WordPressError(f"WordPress {method} {url} devolvió {response.status_code}: {detail}")
                return response
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    break
                time.sleep(min(2 ** attempt, 8))
        raise WordPressError(f"No se pudo conectar con WordPress: {last_error}")

    def json(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        response = self.request(method, endpoint, **kwargs)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise WordPressError(f"WordPress devolvió JSON inválido para {endpoint}") from exc

    def preflight(self, yoast_enabled: bool = True) -> set[str]:
        self.json("GET", "users/me", params={"context": "edit"})
        options = self.request("OPTIONS", "posts").json()
        writable = set(options.get("schema", {}).get("properties", {}).get("meta", {}).get("properties", {}))
        if yoast_enabled:
            required = {"_yoast_wpseo_title", "_yoast_wpseo_metadesc", "_yoast_wpseo_focuskw"}
            if not required.issubset(writable):
                missing = ", ".join(sorted(required - writable))
                raise WordPressError(f"La REST API no permite escribir las metas de Yoast ({missing}); revisa el MU-plugin.")
        return writable

    def resolve_term(self, taxonomy: str, name: str, *, create: bool = False) -> int | None:
        if not name.strip():
            return None
        terms = self.json("GET", taxonomy, params={"search": name, "per_page": 100}) or []
        for term in terms:
            if term.get("name", "").casefold() == name.casefold():
                return int(term["id"])
        if not create:
            return None
        term = self.json("POST", taxonomy, json={"name": name})
        return int(term["id"])

    def upload_media(self, image_path: str | Path, alt_text: str) -> dict[str, Any]:
        path = Path(image_path)
        with path.open("rb") as stream:
            response = self.request(
                "POST", "media", retry_read=False,
                headers={"Content-Disposition": f'attachment; filename="{path.name}"', "Content-Type": "image/webp"},
                data=stream,
            )
        media = response.json()
        media_id = int(media["id"])
        updated = self.json("POST", f"media/{media_id}", retry_read=False, json={
            "alt_text": alt_text, "caption": "", "description": ""
        })
        if updated:
            media = updated
        source = (media.get("media_details", {}).get("sizes", {}).get("full", {}).get("source_url")
                  or media.get("source_url"))
        return {"id": media_id, "url": source, "alt": alt_text}

    def create_post(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.json("POST", "posts", retry_read=False, json=payload)

    def update_post(self, route: str, post_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.json("POST", f"{route}/{post_id}", retry_read=False, json=payload)

    def get_post(self, route: str, post_id: int) -> dict[str, Any]:
        return self.json("GET", f"{route}/{post_id}", params={"context": "edit"})

    def resolve_post_ref(self, target: str) -> PostRef:
        raw = str(target).strip()
        if raw.isdigit():
            return PostRef("posts", int(raw))
        parsed = urlparse(raw)
        query = parse_qs(parsed.query)
        for key in ("post", "p"):
            if query.get(key, [""])[0].isdigit():
                return PostRef("posts", int(query[key][0]))
        # Public permalinks can disclose the REST object in their Link header.
        try:
            host = (parsed.hostname or "").casefold().removeprefix("www.")
            site_host = (urlparse(self.base_url).hostname or "").casefold().removeprefix("www.")
            if (parsed.scheme not in {"http", "https"} or host != site_host):
                raise WordPressError("La URL de optimización debe pertenecer al sitio WordPress de la campaña")
            # Resolve public permalinks without Basic Auth; never send the site's
            # credentials to a user-controlled target URL.
            response = requests.get(raw, timeout=self.timeout, allow_redirects=True)
            if response.ok:
                link = response.headers.get("Link", "")
                match = re.search(r"<[^>]+/wp-json/wp/v2/(posts|pages)/(\d+)[^>]*>;\s*rel=\"alternate\"", link)
                if match:
                    return PostRef(match.group(1), int(match.group(2)))
        except requests.RequestException:
            pass
        slug = unquote(parsed.path.rstrip("/").split("/")[-1])
        if slug:
            for route in ("posts", "pages"):
                found = self.json("GET", route, params={"slug": slug, "status": "any", "context": "edit"}) or []
                if found:
                    return PostRef(route, int(found[0]["id"]))
        raise WordPressError(f"No se pudo resolver el post de {raw}")
