"""Exact input freshness contracts for user-profile projections."""

from __future__ import annotations

from typing import Any

from .models import (
    PROFILE_ASSERTION_FAMILIES,
    PROFILE_ASSERTION_STATES,
    UserProfileProjection,
)

_TIMESTAMP_KEYS = ("updated_at", "last_validated_at", "created_at")
_EPSILON = 0.000001


async def profile_projection_is_stale(
    projection: UserProfileProjection,
    *,
    user_id: str,
    l2_store: Any,
) -> bool:
    """Return whether current profile inputs differ from the stored highwaters."""

    entity_id = f"user:{user_id}"
    assertions = await list_current_profile_assertions(l2_store, entity_id=entity_id)
    if _cached_profile_assertion_is_no_longer_current(projection, assertions):
        return True
    if not highwaters_equal(
        projection.input_assertion_highwater,
        assertion_records_highwater(assertions),
    ):
        return True
    if int(projection.source_revision) != await current_subject_revision(
        l2_store,
        entity_id=entity_id,
    ):
        return True
    return int(projection.source_generation) != await current_clear_generation(l2_store)


def _cached_profile_assertion_is_no_longer_current(
    projection: UserProfileProjection,
    assertions: list[dict[str, Any]],
) -> bool:
    cached_ids = _collect_assertion_ids(projection.field_sources)
    cached_ids.update(_collect_assertion_ids(projection.field_conflicts))
    if not cached_ids:
        return False
    current_ids = {
        str(assertion.get("assertion_id") or "").strip()
        for assertion in assertions
        if str(assertion.get("assertion_id") or "").strip()
    }
    return not cached_ids.issubset(current_ids)


def _collect_assertion_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = {
            assertion_id
            for assertion_id in [str(value.get("assertion_id") or "").strip()]
            if assertion_id
        }
        for nested in value.values():
            found.update(_collect_assertion_ids(nested))
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for nested in value:
            found.update(_collect_assertion_ids(nested))
        return found
    return set()


async def list_current_profile_assertions(
    l2_store: Any,
    *,
    entity_id: str,
) -> list[dict[str, Any]]:
    """Read all current Assertion inputs used by the profile projection."""

    list_assertions = getattr(l2_store, "list_current_assertions", None)
    if not callable(list_assertions):
        raise RuntimeError("L2 current Assertion reads are unavailable")
    assertions = await list_assertions(
        entity_id=entity_id,
        entity_type="user",
        context_scope=None,
        limit=500,
    )
    return [
        assertion
        for assertion in assertions
        if assertion.get("trait_family") in PROFILE_ASSERTION_FAMILIES
        and assertion.get("validation_state") in PROFILE_ASSERTION_STATES
    ][:200]


def assertion_records_highwater(assertions: list[dict[str, Any]]) -> float:
    """Return the newest semantic change timestamp across Assertion records."""

    return records_highwater(assertions, keys=_TIMESTAMP_KEYS)


def profile_projection_highwater(projection: UserProfileProjection | None) -> float:
    """Return the mutation highwater of one stored profile projection."""

    if projection is None:
        return 0.0
    return max(
        float(projection.updated_at or 0.0),
        float(projection.refreshed_at or 0.0),
        float(projection.created_at or 0.0),
    )


def records_highwater(records: Any, *, keys: tuple[str, ...]) -> float:
    """Return the highest numeric timestamp from mapping records."""

    if not isinstance(records, list):
        return 0.0
    highwater = 0.0
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in keys:
            try:
                highwater = max(highwater, float(record.get(key) or 0.0))
            except (TypeError, ValueError):
                continue
    return highwater


async def current_subject_revision(l2_store: Any, *, entity_id: str) -> int:
    """Read the source revision, propagating dependency query failures."""

    getter = getattr(l2_store, "current_subject_revision", None)
    if not callable(getter):
        return 0
    return int(await getter(entity_id))


async def current_clear_generation(l2_store: Any) -> int:
    """Read the clear generation, propagating dependency query failures."""

    getter = getattr(l2_store, "current_clear_generation", None)
    if not callable(getter):
        return 0
    return int(await getter())


def highwaters_equal(left: Any, right: Any) -> bool:
    """Compare timestamp highwaters without treating query failure as zero."""

    return abs(float(left or 0.0) - float(right or 0.0)) <= _EPSILON


__all__ = [
    "assertion_records_highwater",
    "current_clear_generation",
    "current_subject_revision",
    "highwaters_equal",
    "list_current_profile_assertions",
    "profile_projection_highwater",
    "profile_projection_is_stale",
    "records_highwater",
]
