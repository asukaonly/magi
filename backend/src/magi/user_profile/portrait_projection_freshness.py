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
    """Return true when newer profile, assertion, snapshot, or graph input exists."""
    newest_input_at = _profile_timestamp(profile_projection)
    entity_id = f"user:{user_id}"
    if l2_store is not None:
        newest_input_at = max(newest_input_at, await _latest_assertion_timestamp(l2_store, entity_id))
        newest_input_at = max(newest_input_at, await _latest_snapshot_timestamp(l2_store, entity_id))
        newest_input_at = max(newest_input_at, await _latest_relationship_timestamp(l2_store, entity_id))
    projection_at = max(
        _float_value(projection.generated_at),
        _float_value(projection.updated_at),
    )
    return newest_input_at > projection_at + 0.000001


async def _latest_assertion_timestamp(l2_store: Any, entity_id: str) -> float:
    list_assertions = getattr(l2_store, "list_tom_assertions", None)
    if list_assertions is None:
        return 0.0
    try:
        assertions = await list_assertions(
            entity_id=entity_id,
            entity_type="user",
            trait_families=list(PORTRAIT_ASSERTION_FAMILIES),
            include_expired=False,
            limit=1,
        )
    except Exception:
        return 0.0
    return _records_timestamp(assertions, ("updated_at", "last_validated_at", "created_at"))


async def _latest_snapshot_timestamp(l2_store: Any, entity_id: str) -> float:
    list_snapshots = getattr(l2_store, "list_tom_snapshots", None)
    if list_snapshots is None:
        return 0.0
    try:
        snapshots = await list_snapshots(entity_id=entity_id, entity_type="user", limit=1)
    except TypeError:
        try:
            snapshots = await list_snapshots(entity_id=entity_id, limit=1)
        except Exception:
            return 0.0
    except Exception:
        return 0.0
    return _records_timestamp(snapshots, ("last_updated_at", "updated_at", "created_at"))


async def _latest_relationship_timestamp(l2_store: Any, entity_id: str) -> float:
    get_relationships = getattr(l2_store, "get_relationships", None)
    if get_relationships is None:
        return 0.0
    try:
        relationships = await get_relationships(subject_id=entity_id, limit=1)
    except Exception:
        return 0.0
    return _records_timestamp(relationships, ("updated_at", "last_observed_at", "created_at"))


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
