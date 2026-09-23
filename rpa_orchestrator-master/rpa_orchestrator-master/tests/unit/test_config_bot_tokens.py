from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.core.config import Settings

TOKEN_A = "a" * 64
TOKEN_B = "b" * 64
VALID = f'{{"{TOKEN_A}":"saaf-backlinks-01","{TOKEN_B}":"post-bot-prod-01"}}'


def _settings(raw: str) -> Settings:
    return Settings(bot_tokens=raw, _env_file=None)


def test_valid_json_object_is_parsed() -> None:
    settings = _settings(VALID)

    assert settings.bot_tokens == {
        TOKEN_A: "saaf-backlinks-01",
        TOKEN_B: "post-bot-prod-01",
    }


def test_empty_value_means_no_tokens() -> None:
    assert _settings("").bot_tokens == {}
    assert _settings("   ").bot_tokens == {}


def test_a_mapping_passes_through_unchanged() -> None:
    assert Settings(bot_tokens={TOKEN_A: "saaf-backlinks-01"}, _env_file=None).bot_tokens == {
        TOKEN_A: "saaf-backlinks-01"
    }


def test_two_objects_glued_together_explains_the_cause() -> None:
    glued = f'{{"{TOKEN_A}":"saaf-backlinks-01"}}{{"{TOKEN_B}":"post-bot-prod-01"}}'

    with pytest.raises(ValidationError) as excinfo:
        _settings(glued)

    message = str(excinfo.value)
    assert "BOT_TOKENS no es JSON valido" in message
    assert "Extra data" in message
    assert "en vez de agregar la entrada al primero" in message


def test_trailing_comment_is_reported_as_extra_data() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _settings(f"{VALID}  # instagram")

    assert "Extra data" in str(excinfo.value)


def test_quoted_value_is_reported() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _settings(f"'{VALID}'")

    assert "van sin comillas" in str(excinfo.value)


def test_a_json_list_is_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _settings(f'["{TOKEN_A}"]')

    assert "debe ser un objeto JSON" in str(excinfo.value)


@pytest.mark.parametrize(
    "raw",
    [
        f'{{"{TOKEN_A}":"saaf-backlinks-01"}}{{"{TOKEN_B}":"post-bot-prod-01"}}',
        f"{VALID}  # instagram",
        f"'{VALID}'",
    ],
)
def test_the_error_never_echoes_the_tokens(raw: str) -> None:
    """hide_input_in_errors evita que el secreto termine en el log del deploy."""
    with pytest.raises(ValidationError) as excinfo:
        _settings(raw)

    message = str(excinfo.value)
    assert TOKEN_A not in message
    assert TOKEN_B not in message
