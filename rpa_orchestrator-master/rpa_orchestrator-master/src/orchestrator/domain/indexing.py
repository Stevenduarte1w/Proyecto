from __future__ import annotations

from typing import Any

INDEXING_CAPABILITY = "indexing.submit"
INDEXING_STAGE = "indexing_submit"
INDEXING_INPUT_SCHEMA = "indexing.submit.input.v1"
INDEXING_RESULT_SCHEMA = "indexing.result.v1"


def indexing_result_error(payload: dict[str, Any] | bool) -> str | None:
    if not isinstance(payload, dict):
        return "Indexing result must be a JSON object"
    if payload.get("schema_version") != INDEXING_RESULT_SCHEMA:
        return f"Indexing result requires schema_version={INDEXING_RESULT_SCHEMA}"
    if payload.get("ok") is not True:
        return "Indexing result requires ok=true"
    if payload.get("status") != "submitted":
        return "Indexing result requires status=submitted"
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return "Indexing result requires a summary object"
    required_counts = (
        "urls_received",
        "urls_indexable",
        "urls_submitted",
        "urls_blocked",
    )
    invalid_counts = [
        field
        for field in required_counts
        if not isinstance(summary.get(field), int)
        or isinstance(summary.get(field), bool)
        or summary[field] < 0
    ]
    if invalid_counts:
        return f"Indexing summary has invalid counts: {', '.join(invalid_counts)}"
    return None
