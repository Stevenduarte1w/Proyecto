from __future__ import annotations

import base64
import hmac
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.v1.dependencies import db_session
from orchestrator.core.config import get_settings
from orchestrator.domain.entities import Execution
from orchestrator.infrastructure.bots.auth import authenticated_bot_key, is_page_flow_bot
from orchestrator.infrastructure.postgres.repositories import (
    SqlAlchemyBotRepository,
    SqlAlchemyExecutionRepository,
)


@dataclass(frozen=True, slots=True)
class BotExecutionPrincipal:
    bot_id: UUID
    bot_key: str


async def require_bot_execution_access(
    execution_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(db_session)],
) -> BotExecutionPrincipal:
    execution_repository = SqlAlchemyExecutionRepository(session)
    bot_repository = SqlAlchemyBotRepository(session)
    bot_key = authenticated_bot_key(
        request.headers.get("Authorization"),
        get_settings(),
    )
    if bot_key is None:
        execution = await execution_repository.get(execution_id)
        if execution is not None and _allows_tokenless_page_flow_access(execution):
            if execution.bot_id is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Execution has not been assigned to a bot",
                )
            assigned_bot = await bot_repository.get(execution.bot_id)
            if (
                assigned_bot is None
                or not assigned_bot.enabled
                or execution.requested_capability not in assigned_bot.capabilities
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Execution bot is not available for this capability",
                )
            return BotExecutionPrincipal(
                bot_id=assigned_bot.id,
                bot_key=assigned_bot.bot_key,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": 'Bearer realm="RPA Bots"'},
        )
    bot = await bot_repository.get_by_key(bot_key)
    if bot is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown bot")
    execution = await execution_repository.get(execution_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    if execution.bot_id != bot.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Execution is assigned to a different bot",
        )
    return BotExecutionPrincipal(bot_id=bot.id, bot_key=bot.bot_key)


def _allows_tokenless_page_flow_access(execution: Execution) -> bool:
    return execution.step_id is not None and is_page_flow_bot(
        [execution.requested_capability]
    )


def require_dashboard_operator(request: Request) -> None:
    settings = get_settings()
    if not settings.dashboard_user or not settings.dashboard_pass:
        return
    authorization = request.headers.get("Authorization", "")
    if _valid_basic_auth(
        authorization,
        settings.dashboard_user,
        settings.dashboard_pass,
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": 'Basic realm="SEO Dashboard"'},
    )


def require_dashboard_or_bot_token(request: Request) -> None:
    """Acepta al operador del dashboard o a un worker con token de BOT_TOKENS.

    La UI crea ejecuciones autonomas con Basic auth y el adaptador Django lo
    hace con su token de worker; ambos caminos son legitimos. Si no hay
    credenciales de dashboard configuradas se comporta igual que el resto del
    panel y deja pasar.
    """
    if authenticated_bot_key(request.headers.get("Authorization"), get_settings()) is not None:
        return
    require_dashboard_operator(request)


def _valid_basic_auth(header: str, expected_user: str, expected_password: str) -> bool:
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
        user, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(user, expected_user) and hmac.compare_digest(
        password,
        expected_password,
    )
