"""Freshness checks for user portrait projections."""

from __future__ import annotations

from typing import Any

from .models import UserPortraitProjection, UserProfileProjection
from .portrait_claim_query import (
    latest_portrait_claim_change_at,
    list_tentative_portrait_claims,
)
from .portrait_projection_builder import PORTRAIT_ASSERTION_FAMILIES
from .portrait_signal_policy import assertion_portrait_role


async def portrait_projection_is_stale(
    projection: UserPortraitProjection,
    *,
    user_id: str,
    l2_store: Any,
    profile_projection: UserProfileProjection | None = None,
) -> bool:
    """Return true when a newer or no-longer-visible portrait input exists."""
    if _missing_correction_version_metadata(projection):
        return True
    entity_id = f"user:{user_id}"
    if await _source_revision_changed(projection, l2_store, entity_id):
        return True
    if await _clear_generation_changed(projection, l2_store):
        return True

    newest_input_at = _profile_timestamp(profile_projection)
    assertions: list[dict[str, Any]] = []
    if l2_store is not None:
        assertions = await _current_portrait_assertions(l2_store, entity_id)
        if _cached_assertion_is_no_longer_current(projection, assertions):
            return True
        newest_input_at = max(
            newest_input_at,
            _records_timestamp(assertions, ("updated_at", "last_validated_at", "created_at")),
            await latest_portrait_claim_change_at(l2_store, user_id=user_id),
        )
        if await _cached_tentative_line_is_no_longer_current(
            projection,
            l2_store=l2_store,
            user_id=user_id,
            assertions=assertions,
        ):
            return True
    projection_at = max(
        _float_value(projection.generated_at),
        _float_value(projection.updated_at),
    )
    return newest_input_at > projection_at + 0.000001


def _cached_assertion_is_no_longer_current(
    projection: UserPortraitProjection,
    assertions: list[dict[str, Any]],
) -> bool:
    cached_ids: set[str] = set()
    for group in (projection.world or {}).get("groups") or []:
        if isinstance(group, dict):
            cached_ids.update(_assertion_ids(group.get("items")))
    cached_ids.update(_assertion_ids((projection.review or {}).get("items")))
    cached_ids.update(_assertion_ids((projection.recent or {}).get("items")))
    if not cached_ids:
        return False
    current_ids = {
        str(assertion.get("assertion_id") or "").strip()
        for assertion in assertions
        if str(assertion.get("assertion_id") or "").strip()
    }
    return not cached_ids.issubset(current_ids)


def _assertion_ids(items: Any) -> set[str]:
    if not isinstance(items, list):
        return set()
    return {
        assertion_id
        for item in items
        if isinstance(item, dict) and (assertion_id := str(item.get("assertion_id") or "").strip())
    }


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


async def _current_portrait_assertions(
    l2_store: Any,
    entity_id: str,
) -> list[dict[str, Any]]:
    list_assertions = getattr(l2_store, "list_current_assertions", None)
    if list_assertions is None:
        return []
    try:
        assertions = await list_assertions(
            entity_id=entity_id,
            entity_type="user",
            context_scope=None,
            limit=500,
        )
    except Exception:
        return []
    return [
        assertion
        for assertion in assertions
        if assertion.get("trait_family") in PORTRAIT_ASSERTION_FAMILIES
    ]


async def _cached_tentative_line_is_no_longer_current(
    projection: UserPortraitProjection,
    *,
    l2_store: Any,
    user_id: str,
    assertions: list[dict[str, Any]],
) -> bool:
    cached_lines = {
        str(line).strip()
        for line in projection.prompt_summary
        if str(line).strip().startswith("用户曾自述：")
    }
    if not cached_lines:
        return False
    current_assertion_ids = {
        str(assertion.get("assertion_id") or "").strip()
        for assertion in assertions
        if str(assertion.get("assertion_id") or "").strip()
    }
    visible_assertion_ids = {
        str(assertion.get("assertion_id") or "").strip()
        for assertion in assertions
        if assertion_portrait_role(assertion) in {"world", "recent"}
        and str(assertion.get("assertion_id") or "").strip()
    }
    candidates = await list_tentative_portrait_claims(
        l2_store,
        user_id=user_id,
        current_assertion_ids=current_assertion_ids,
        visible_assertion_ids=visible_assertion_ids,
    )
    current_lines = {candidate.prompt_line for candidate in candidates}
    return not cached_lines.issubset(current_lines)


async def _source_revision_changed(
    projection: UserPortraitProjection,
    l2_store: Any,
    entity_id: str,
) -> bool:
    getter = getattr(l2_store, "current_subject_revision", None)
    if not callable(getter):
        return False
    try:
        return int(await getter(entity_id)) != int(projection.source_revision)
    except Exception:
        return False


async def _clear_generation_changed(
    projection: UserPortraitProjection,
    l2_store: Any,
) -> bool:
    getter = getattr(l2_store, "current_clear_generation", None)
    if not callable(getter):
        return False
    try:
        return int(await getter()) != int(projection.source_generation)
    except Exception:
        return False


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
