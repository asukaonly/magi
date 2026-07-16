"""Freshness checks for user portrait projections."""

from __future__ import annotations

from typing import Any

from .models import UserPortraitProjection, UserProfileProjection
from .portrait_projection_builder import PORTRAIT_ASSERTION_FAMILIES


async def portrait_projection_is_stale(
    projection: UserPortraitProjection,
    *,
    user_id: str,
    l2_store: Any,
    profile_projection: UserProfileProjection | None = None,
) -> bool:
    """Return true when a newer profile or governed assertion input exists."""
    if _missing_correction_version_metadata(projection):
        return True
    newest_input_at = _profile_timestamp(profile_projection)
    entity_id = f"user:{user_id}"
    if l2_store is not None:
        newest_input_at = max(newest_input_at, await _latest_assertion_timestamp(l2_store, entity_id))
    projection_at = max(
        _float_value(projection.generated_at),
        _float_value(projection.updated_at),
    )
    return newest_input_at > projection_at + 0.000001


def _missing_correction_version_metadata(projection: UserPortraitProjection) -> bool:
    """Invalidate portrait caches missing lossless correction metadata.

    Assertion-backed portrait items need their source ``updated_at`` value for
    optimistic concurrency checks and their stored ``correction_value`` so a
    display-formatted value is never written back as a different assertion. A
    rebuilt projection persists both values, after which normal timestamp
    freshness checks apply.
    """
    containers: list[Any] = []
    for group in (projection.world or {}).get("groups") or []:
        if not isinstance(group, dict):
            return True
        containers.append(group.get("items") or [])
    containers.extend(
        [
            (projection.review or {}).get("items") or [],
            (projection.recent or {}).get("items") or [],
        ]
    )
    for items in containers:
        if not isinstance(items, list):
            return True
        for item in items:
            if not isinstance(item, dict) or not item.get("assertion_id"):
                continue
            if not _float_value(item.get("updated_at")) > 0.0:
                return True
            if "correction_value" not in item:
                return True
    return False


async def _latest_assertion_timestamp(l2_store: Any, entity_id: str) -> float:
    list_assertions = getattr(l2_store, "list_current_assertions", None)
    if list_assertions is None:
        return 0.0
    try:
        assertions = await list_assertions(
            entity_id=entity_id,
            entity_type="user",
            context_scope=None,
            limit=500,
        )
    except Exception:
        return 0.0
    current = [
        assertion
        for assertion in assertions
        if assertion.get("trait_family") in PORTRAIT_ASSERTION_FAMILIES
    ]
    return _records_timestamp(current, ("updated_at", "last_validated_at", "created_at"))


def _profile_timestamp(profile: UserProfileProjection | None) -> float:
    if profile is None:
        return 0.0
    return max(
        _float_value(profile.updated_at),
        _float_value(profile.refreshed_at),
        _float_value(profile.created_at),
    )


def _records_timestamp(records: Any, keys: tuple[str, ...]) -> float:
    if not isinstance(records, list):
        return 0.0
    best = 0.0
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in keys:
            best = max(best, _float_value(record.get(key)))
    return best


def _float_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["portrait_projection_is_stale"]
