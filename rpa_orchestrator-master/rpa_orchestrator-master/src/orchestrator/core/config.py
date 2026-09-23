from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # hide_input_in_errors evita que un valor invalido termine impreso en el
    # traceback: casi todos los campos de aqui son secretos.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "RPA Orchestrator"
    app_env: str = "local"
    app_debug: bool = False
    api_v1_prefix: str = "/api/v1"

    postgres_dsn: str = Field(
        default="postgresql+asyncpg://orchestrator:orchestrator@localhost:5432/orchestrator"
    )
    seo_agent_dsn: str | None = None
    mongo_dsn: str = "mongodb://localhost:27017"
    mongo_database: str = "seo_flows"
    redis_dsn: str = "redis://localhost:6379/0"
    dashboard_user: str = ""
    dashboard_pass: str = ""
    bot_tokens: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict)
    post_monitor_ws_token: str = ""

    # Backend Django que actua como catalogo de Instagram.
    instagram_backend_url: str = ""
    instagram_backend_token: str = ""

    bot_request_timeout_seconds: float = 30.0
    bot_max_retries: int = 3
    execution_lock_ttl_seconds: int = 900
    bot_presence_ttl_seconds: int = 60
    bot_heartbeat_grace_seconds: int = Field(default=60, ge=10)
    bot_reconciliation_interval_seconds: int = Field(default=15, ge=1)
    page_execution_log_ttl_seconds: int = 86400
    post_monitor_presence_ttl_seconds: int = Field(default=60, ge=10)
    post_monitor_max_message_bytes: int = Field(default=262_144, ge=1_024)
    post_bot_presence_ttl_seconds: int = Field(default=60, ge=10)
    post_bot_max_message_bytes: int = Field(default=262_144, ge=1_024)

    brightlocal_api_key: str = ""
    brightlocal_api_base_url: str = "https://api.brightlocal.com"
    brightlocal_rank_num_results: int = Field(default=100, ge=1, le=100)
    brightlocal_rank_timeout_seconds: float = Field(default=45.0, gt=0)
    brightlocal_rank_poll_interval_seconds: float = Field(default=1.5, gt=0)

    rank_provider: Literal["serper", "brightlocal"] = "serper"
    serper_api_key: str = ""
    serper_api_base_url: str = "https://google.serper.dev"
    serper_rank_num_results: int = Field(default=100, ge=1, le=100)
    serper_request_timeout_seconds: float = Field(default=15.0, gt=0)

    @field_validator("bot_tokens", mode="before")
    @classmethod
    def parse_bot_tokens(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(_bot_tokens_hint(text, exc)) from exc
        if not isinstance(parsed, dict):
            raise ValueError(
                "BOT_TOKENS debe ser un objeto JSON token -> bot_key, "
                f"no {type(parsed).__name__}"
            )
        return parsed

    @field_validator("seo_agent_dsn", mode="before")
    @classmethod
    def empty_seo_agent_dsn_is_none(cls, value: object) -> object:
        return None if value == "" else value


def _bot_tokens_hint(text: str, error: json.JSONDecodeError) -> str:
    """Explica un BOT_TOKENS malformado sin revelar su contenido."""
    detail = (
        f"BOT_TOKENS no es JSON valido: {error.msg} en el caracter {error.pos} "
        f"de {len(text)}."
    )
    if error.msg == "Extra data":
        detail += (
            " Hay un objeto JSON completo y despues sobra texto: suele pasar al"
            " pegar un segundo objeto en vez de agregar la entrada al primero,"
            " o al dejar un comentario al final de la linea."
        )
    elif text[0] in "'\"" and text[-1] in "'\"":
        detail += " El valor parece estar entre comillas; van sin comillas en el .env."
    detail += (
        ' Todas las entradas van dentro del mismo objeto:'
        ' BOT_TOKENS={"token-a":"bot-key-a","token-b":"bot-key-b"}'
    )
    return detail


@lru_cache
def get_settings() -> Settings:
    return Settings()
