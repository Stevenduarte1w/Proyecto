from __future__ import annotations

from typing import Final

POST_CREATE_CAPABILITY: Final = "posts.create"
POST_OPTIMIZE_CAPABILITY: Final = "posts.optimize"

POST_BOT_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        POST_CREATE_CAPABILITY,
        POST_OPTIMIZE_CAPABILITY,
    }
)

QUEUED: Final = "queued"
DISPATCHED: Final = "dispatched"
RUNNING: Final = "running"
SUCCEEDED: Final = "succeeded"
FAILED: Final = "failed"
CANCELLED: Final = "cancelled"

POST_BOT_JOB_STATES: Final[frozenset[str]] = frozenset(
    {QUEUED, DISPATCHED, RUNNING, SUCCEEDED, FAILED, CANCELLED}
)
POST_BOT_TERMINAL_STATES: Final[frozenset[str]] = frozenset({SUCCEEDED, FAILED, CANCELLED})
POST_BOT_ACTIVE_STATES: Final[frozenset[str]] = frozenset({DISPATCHED, RUNNING})
