"""Freshness checks for user portrait projections."""

from __future__ import annotations

import inspect
from typing import Any

from .models import UserPortraitProjection, UserProfileProjection
from .portrait_claim_query import (
    latest_portrait_claim_change_at,
    list_tentative_portrait_claims,
)
from .portrait_projection_builder import (
    PORTRAIT_ASSERTION_FAMILIES,
    TENTATIVE_SELECTION_REF_PREFIX,
    render_portrait_rule_prompt_summary,
    select_rendered_tentative_portrait_claims,
    tentative_portrait_selection_refs,
)
from .portrait_signal_policy import assertion_portrait_role
from .projection_freshness import (
    assertion_records_highwater,
    current_clear_generation,
    current_subject_revision,
    highwaters_equal,
    profile_projection_highwater,
)


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
    if int(projection.source_revision) != await current_subject_revision(
        l2_store,
        entity_id=entity_id,
    ):
        return True
    if int(projection.source_generation) != await current_clear_generation(l2_store):
        return True

    assertions = await _current_portrait_assertions(l2_store, entity_id)
    if not highwaters_equal(
        projection.input_assertion_highwater,
        assertion_records_highwater(assertions),
    ):
        return True
    if _cached_assertion_is_no_longer_current(projection, assertions):
        return True
    if not highwaters_equal(
        projection.input_claim_highwater,
        await latest_portrait_claim_change_at(l2_store, user_id=user_id),
    ):
        return True
    if not highwaters_equal(
        projection.input_review_highwater,
        await _latest_review_change_at(l2_store, entity_id=entity_id),
    ):
        return True
    if not highwaters_equal(
        projection.input_profile_highwater,
        profile_projection_highwater(profile_projection),
    ):
        return True
    return await _tentative_prompt_selection_changed(
        projection,
        l2_store=l2_store,
        user_id=user_id,
        assertions=assertions,
    )


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
        if assertion.get("trait_family") in PORTRAIT_ASSERTION_FAMILIES
    ]


async def _tentative_prompt_selection_changed(
    projection: UserPortraitProjection,
    *,
    l2_store: Any,
    user_id: str,
    assertions: list[dict[str, Any]],
) -> bool:
    cached_lines = [
        str(line).strip()
        for line in projection.prompt_summary
        if str(line).strip().startswith("用户曾自述：")
    ]
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
    current_candidate_lines = [candidate.prompt_line for candidate in candidates[:2]]
    current_summary = render_portrait_rule_prompt_summary(
        world=projection.world,
        recent=projection.recent,
        tentative_lines=current_candidate_lines,
    )
    current_lines = [
        str(line).strip()
        for line in current_summary
        if str(line).strip().startswith("用户曾自述：")
    ]
    current_selection = select_rendered_tentative_portrait_claims(
        candidates[:2],
        current_summary,
    )
    current_selection_refs = tentative_portrait_selection_refs(current_selection)
    cached_selection_refs = [
        str(reference).strip()
        for reference in projection.evidence_refs
        if str(reference).strip().startswith(TENTATIVE_SELECTION_REF_PREFIX)
    ]
    return cached_lines != current_lines or cached_selection_refs != current_selection_refs


async def _latest_review_change_at(l2_store: Any, *, entity_id: str) -> float:
    if inspect.getattr_static(
        l2_store,
        "latest_pending_review_change_at",
        None,
    ) is None:
        return 0.0
    getter = getattr(l2_store, "latest_pending_review_change_at", None)
    if not callable(getter):
        return 0.0
    return float(await getter(subject_id=entity_id) or 0.0)


def _float_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["portrait_projection_is_stale"]
