from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from orchestrator.core.config import get_settings

_engine: AsyncEngine | None = None


def get_seo_agent_engine() -> AsyncEngine:
    global _engine
    settings = get_settings()
    if settings.seo_agent_dsn is None:
        raise RuntimeError(
            "SEO_AGENT_DSN is not configured for the seo_agent_deep_seek database"
        )
    if _engine is None:
        _engine = create_async_engine(settings.seo_agent_dsn, pool_pre_ping=True)
    return _engine


async def dispose_seo_agent_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
