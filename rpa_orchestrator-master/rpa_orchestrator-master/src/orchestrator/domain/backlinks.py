from __future__ import annotations

BACKLINKS_CAPABILITY = "backlinks.saaf"
BACKLINKS_STAGE = "backlinks_pipeline"

BACKLINK_EVENT_TYPES = frozenset(
    {
        "run.start",
        "stage.start",
        "stage.end",
        "site.start",
        "site.done",
        "stats",
        "log",
        "run.end",
        "error",
    }
)
