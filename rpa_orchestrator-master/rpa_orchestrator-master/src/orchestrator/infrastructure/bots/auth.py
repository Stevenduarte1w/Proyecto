from __future__ import annotations

import hmac
from collections.abc import Iterable

from orchestrator.core.config import Settings

PAGE_FLOW_BOT_CAPABILITIES = frozenset(
    {
        "wordpress.page_upsert",
        "seo.main",
        "posts.create",
        "video.create",
        "pagespeed.check",
        "indexing.submit",
    }
)


def is_page_flow_bot(capabilities: Iterable[str]) -> bool:
    requested_capabilities = {
        capability.strip() for capability in capabilities if capability.strip()
    }
    return bool(requested_capabilities) and requested_capabilities.issubset(
        PAGE_FLOW_BOT_CAPABILITIES
    )


def authenticated_bot_key(
    authorization_header: str | None,
    settings: Settings,
) -> str | None:
    token = bearer_token(authorization_header)
    if token is None:
        return None
    for configured_token, configured_bot_key in settings.bot_tokens.items():
        if hmac.compare_digest(token, configured_token):
            return configured_bot_key
    return None


def bot_registration_is_authorized(
    authorization_header: str | None,
    bot_key: str,
    settings: Settings,
) -> bool:
    authenticated_key = authenticated_bot_key(authorization_header, settings)
    return authenticated_key is not None and hmac.compare_digest(bot_key, authenticated_key)


def websocket_transport_is_secure(
    *,
    app_env: str,
    websocket_scheme: str,
    forwarded_proto: str | None,
) -> bool:
    if app_env.strip().lower() not in {"production", "prod"}:
        return True
    effective_scheme = (forwarded_proto or websocket_scheme).split(",", 1)[0].strip().lower()
    return effective_scheme in {"https", "wss"}


def bearer_token(authorization_header: str | None) -> str | None:
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return None
    token = authorization_header[7:].strip()
    return token or None
