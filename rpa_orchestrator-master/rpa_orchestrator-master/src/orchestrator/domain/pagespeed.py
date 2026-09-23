from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PAGESPEED_CAPABILITY = "pagespeed.check"
PAGESPEED_PROFILES = ("mobile", "desktop")


def indexing_denial_reason(payload: Mapping[str, Any]) -> str | None:
    missing_profiles = tuple(
        profile for profile in PAGESPEED_PROFILES if profile not in payload
    )
    if missing_profiles:
        return f"PageSpeed result is missing profiles: {', '.join(missing_profiles)}"

    invalid_profiles = tuple(
        profile
        for profile in PAGESPEED_PROFILES
        if not isinstance(payload.get(profile), Mapping)
    )
    if invalid_profiles:
        return (
            "PageSpeed profiles must be JSON objects: "
            f"{', '.join(invalid_profiles)}"
        )

    invalid_can_index = tuple(
        profile
        for profile in PAGESPEED_PROFILES
        if not isinstance(payload[profile].get("can_index"), bool)
    )
    if invalid_can_index:
        return (
            "PageSpeed profiles require boolean can_index: "
            f"{', '.join(invalid_can_index)}"
        )

    denied_profiles = tuple(
        profile for profile in PAGESPEED_PROFILES if _profile_denies_indexing(payload.get(profile))
    )
    if not denied_profiles:
        return None

    profiles = ", ".join(denied_profiles)
    return (
        f"Indexing blocked: PageSpeed did not authorize indexing (can_index=false for: {profiles})"
    )


def _profile_denies_indexing(profile_result: Any) -> bool:
    return isinstance(profile_result, Mapping) and profile_result.get("can_index") is False
