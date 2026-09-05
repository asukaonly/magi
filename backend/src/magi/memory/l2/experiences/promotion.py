"""Seed-driven promotion from episode substrate to L2 experiences."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
import uuid
from typing import Any

from ..storage.utils import _l2_setting
from .models import ExperiencePromotionStats
from .seed_discovery import (
    discover_experience_seeds,
    is_generic_experience_anchor,
    is_technical_artifact_experience_token,
)
from .quality import evaluate_experience_quality
from .seed_recall import recall_candidate_evidence_for_seed
from .seed_selection import SelectionProvider, select_experience_from_seed

DUPLICATE_OVERLAP_RATIO = 0.8
MIN_CANDIDATE_SEED_CONFIDENCE = 0.6
LEGACY_GENERIC_INTERPRETATION = "magi grouped related episode evidence into a narratable memory."


@dataclass(frozen=True)
class SeedPromotionOutcome:
    processed: int = 0
    promoted: int = 0
    skipped_duplicates: int = 0
    rejected: int = 0
    deferred: int = 0
    promoted_experience_id: str | None = None
    included_episode_ids: list[str] = field(default_factory=list)


class ExperienceSelectionDeferred(RuntimeError):
    """The run exhausted its model budget; keep the candidate for another run."""


def _ordered_unique(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _concrete(values: list[Any]) -> list[str]:
    return _ordered_unique([value for value in values if not is_generic_experience_anchor(value)])


def _experience_has_only_generic_anchors(experience: dict[str, Any]) -> bool:
    raw_values = [
        value
        for key in ("primary_entity_ids", "primary_place_ids", "primary_topic_keys")
        for value in (experience.get(key) or [])
    ]
    return bool(raw_values) and not _concrete(raw_values)


def _looks_like_legacy_source_dump(value: Any) -> bool:
    text = str(value or "").strip().casefold()
    if not text:
        return False
    if text.count("/") >= 2 and any(token in text for token in ("chrome", "google", "github")):
        return True
    return "chrome 浏览" in text or "google search" in text


def _is_bad_legacy_experience(experience: dict[str, Any]) -> bool:
    if experience.get("source_seed_id"):
        return False
    title = str(experience.get("title") or "")
    interpretation = str(experience.get("magi_interpretation") or "").strip().casefold()
    return (
        interpretation == LEGACY_GENERIC_INTERPRETATION
        or _experience_has_only_generic_anchors(experience)
        or _looks_like_legacy_source_dump(title)
    )


def _is_user_curated_experience(experience: dict[str, Any]) -> bool:
    return bool(
        experience.get("user_label")
        or experience.get("user_note")
        or experience.get("user_cover_asset_ref")
        or experience.get("user_pinned")
    )


def _is_bad_seed_generated_experience(experience: dict[str, Any]) -> bool:
    if not experience.get("source_seed_id") or _is_user_curated_experience(experience):
        return False
    values: list[Any] = [
        experience.get("title"),
        experience.get("intent"),
        experience.get("outcome"),
        experience.get("magi_interpretation"),
    ]
    for key in ("primary_entity_ids", "primary_place_ids", "primary_topic_keys"):
        values.extend(experience.get(key) or [])
    return any(is_technical_artifact_experience_token(value) for value in values)


async def _hide_bad_existing_experiences(store: Any) -> int:
    hidden = 0
    now = time.time()
    for experience in await store.list_experiences(status="active", limit=500):
        is_bad_seed_generated = _is_bad_seed_generated_experience(experience)
        if not (_is_bad_legacy_experience(experience) or is_bad_seed_generated):
            continue
        updated = await store.update_experience(
            experience_id=str(experience["experience_id"]),
            expected_status="active",
            status="hidden",
            last_recomputed_at=now,
        )
        if updated and is_bad_seed_generated:
            seed_id = str(experience.get("source_seed_id") or "").strip()
            if seed_id:
                await store.update_experience_seed(
                    seed_id=seed_id,
                    status="rejected",
                    promoted_experience_id=None,
                    last_evaluated_at=now,
                )
        hidden += int(updated)
    return hidden


async def _existing_active_episode_member_sets(store: Any) -> list[set[str]]:
    existing: list[set[str]] = []
    for experience in await store.list_experiences(status="active", limit=500):
        members = await store.list_experience_members(
            experience_id=str(experience["experience_id"])
        )
        episode_ids = {
            str(member["member_id"])
            for member in members
            if member["member_type"] == "episode" and member["role"] != "excluded"
        }
        if episode_ids:
            existing.append(episode_ids)
    return existing


def _is_duplicate(included_episode_ids: list[str], existing_sets: list[set[str]]) -> bool:
    candidate_ids = set(included_episode_ids)
    if not candidate_ids:
        return False
    duplicate_ratio = float(
        _l2_setting("experience", "duplicate_overlap_ratio", DUPLICATE_OVERLAP_RATIO)
    )
    for existing in existing_sets:
        overlap = len(candidate_ids & existing) / min(len(candidate_ids), len(existing))
        if overlap >= duplicate_ratio:
            return True
    return False


def _selection_entities(seed: dict[str, Any], selection: Any) -> list[str]:
    return selection.primary_entity_ids or _concrete(seed.get("anchor_entity_ids") or [])


def _selection_places(seed: dict[str, Any], selection: Any) -> list[str]:
    return selection.primary_place_ids or _concrete(seed.get("anchor_place_ids") or [])


def _selection_topics(seed: dict[str, Any], selection: Any) -> list[str]:
    return selection.primary_topic_keys or _concrete(seed.get("anchor_topic_keys") or [])


def _seed_processing_key(seed: dict[str, Any]) -> tuple[int, int, float, float]:
    status_rank = 0 if str(seed.get("status") or "") == "accepted" else 1
    type_rank = {
        "manual": 0,
        "project": 1,
        "repeated_goal": 2,
    }.get(str(seed.get("seed_type") or ""), 9)
    confidence_rank = -float(seed.get("confidence") or 0.0)
    time_rank = float(seed.get("time_start") or 0.0)
    return status_rank, type_rank, confidence_rank, time_rank


async def _reject_seed(store: Any, *, seed_id: str, reason: str, status: str = "rejected") -> None:
    await store.update_experience_seed(
        seed_id=seed_id,
        expected_statuses=["candidate", "accepted"],
        status=status,
        description=f"Rejected: {reason}",
        last_evaluated_at=time.time(),
    )


async def _promote_seed_selection(
    store: Any,
    *,
    seed: dict[str, Any],
    selection: Any,
) -> str:
    experience_id = str(uuid.uuid4())
    await store.create_experience(
        experience_id=experience_id,
        status="active",
        title=selection.title,
        time_start=float(selection.time_start),
        time_end=float(selection.time_end),
        intent=selection.title,
        magi_interpretation=selection.one_sentence_review,
        narrative_score=float(selection.confidence),
        primary_entity_ids=_selection_entities(seed, selection),
        primary_place_ids=_selection_places(seed, selection),
        primary_topic_keys=_selection_topics(seed, selection),
        source_episode_count=len(selection.included_episode_ids),
        source_event_count=0,
        source_seed_id=str(seed["seed_id"]),
        validate_source_seed=True,
    )
    members: list[dict[str, Any]] = [
        {
            "member_type": "episode",
            "member_id": episode_id,
            "role": "core",
            "confidence": float(selection.confidence),
        }
        for episode_id in selection.included_episode_ids
    ]
    members.extend(
        {
            "member_type": str(item.get("ref_type") or "episode"),
            "member_id": str(item.get("ref_id") or ""),
            "role": "excluded",
            "confidence": 0.0,
        }
        for item in selection.excluded_refs
        if str(item.get("ref_type") or "episode") in {"episode", "event"}
        and str(item.get("ref_id") or "").strip()
    )
    added = await store.add_experience_members(
        experience_id=experience_id,
        members=members,
        expected_status="active",
    )
    if added != len(members):
        await store.update_experience(
            experience_id=experience_id,
            expected_status="active",
            status="invalidated",
            last_recomputed_at=time.time(),
        )
        raise ValueError("Experience sources changed during promotion")
    await store.recompute_experience_counts(experience_id=experience_id)
    finalized = await store.update_experience_seed(
        seed_id=str(seed["seed_id"]),
        expected_statuses=["candidate", "accepted"],
        status="promoted",
        promoted_experience_id=experience_id,
        confidence=float(selection.confidence),
        last_evaluated_at=time.time(),
    )
    if not finalized:
        await store.update_experience(
            experience_id=experience_id,
            expected_status="active",
            status="invalidated",
            last_recomputed_at=time.time(),
        )
        raise ValueError("Experience seed changed during promotion")
    return experience_id


async def _load_promotion_seeds(
    store: Any,
    *,
    repeated_goal_selector: Any | None = None,
    target_seed_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    if target_seed_id:
        seed = await store.get_experience_seed(seed_id=target_seed_id)
        return ([seed] if seed is not None else []), 0

    discovery_stats = await discover_experience_seeds(
        store,
        repeated_goal_selector=repeated_goal_selector,
    )
    seeds = await store.list_experience_seeds(
        statuses=["accepted", "candidate"],
        limit=500,
    )
    return sorted(seeds, key=_seed_processing_key), discovery_stats.candidates


async def _promote_single_seed(
    store: Any,
    *,
    seed: dict[str, Any],
    selector: SelectionProvider | None,
    existing_sets: list[set[str]],
) -> SeedPromotionOutcome:
    if str(seed.get("status") or "") not in {"candidate", "accepted"}:
        return SeedPromotionOutcome()
    if seed.get("promoted_experience_id"):
        return SeedPromotionOutcome()
    if _candidate_confidence_below_threshold(seed):
        await _reject_seed(
            store,
            seed_id=str(seed["seed_id"]),
            reason="Candidate confidence is below the promotion threshold.",
        )
        return SeedPromotionOutcome(rejected=1)

    pack = await recall_candidate_evidence_for_seed(store, seed_id=str(seed["seed_id"]))
    try:
        selection = await select_experience_from_seed(
            seed=pack["seed"],
            evidence_pack=pack,
            selector=selector,
        )
    except ExperienceSelectionDeferred:
        return SeedPromotionOutcome(deferred=1)
    if not _selection_can_form_experience(selection):
        await _reject_seed(
            store,
            seed_id=str(seed["seed_id"]),
            reason=selection.reason or "Selection did not form an experience.",
        )
        return SeedPromotionOutcome(processed=1, rejected=1)

    quality = evaluate_experience_quality(
        seed=pack["seed"],
        selection=selection,
        evidence_pack=pack,
    )
    if not quality.accepted:
        await _reject_seed(store, seed_id=str(seed["seed_id"]), reason=quality.reason)
        return SeedPromotionOutcome(processed=1, rejected=1)

    if _is_duplicate(selection.included_episode_ids, existing_sets):
        await _reject_seed(
            store,
            seed_id=str(seed["seed_id"]),
            status="stale",
            reason="Duplicate of an existing experience.",
        )
        return SeedPromotionOutcome(processed=1, skipped_duplicates=1)

    try:
        experience_id = await _promote_seed_selection(
            store,
            seed=seed,
            selection=selection,
        )
    except ValueError:
        return SeedPromotionOutcome(processed=1)
    return SeedPromotionOutcome(
        processed=1,
        promoted=1,
        promoted_experience_id=experience_id,
        included_episode_ids=list(selection.included_episode_ids),
    )


def _limit_selector_calls(
    selector: SelectionProvider | None,
    *,
    max_selector_calls: int | None,
) -> SelectionProvider | None:
    """Wrap selector so automatic runs cannot spend unbounded time on LLM calls."""
    if selector is None or max_selector_calls is None:
        return selector
    remaining = max(0, int(max_selector_calls))

    async def limited_selector(
        seed: dict[str, Any], evidence_pack: dict[str, Any]
    ) -> dict[str, Any]:
        nonlocal remaining
        if remaining <= 0:
            raise ExperienceSelectionDeferred("selector_budget_exhausted")
        remaining -= 1
        result = selector(seed, evidence_pack)
        if hasattr(result, "__await__"):
            return await result
        return dict(result or {})

    return limited_selector


def _candidate_confidence_below_threshold(seed: dict[str, Any]) -> bool:
    return (
        str(seed.get("status") or "") == "candidate"
        and float(seed.get("confidence") or 0.0) < MIN_CANDIDATE_SEED_CONFIDENCE
    )


def _selection_can_form_experience(selection: Any) -> bool:
    return (
        bool(selection.is_experience)
        and bool(selection.included_episode_ids)
        and selection.time_start is not None
        and selection.time_end is not None
    )


def _promotion_stats(
    *,
    outcomes: list[SeedPromotionOutcome],
    discovery_candidates: int,
    active_episode_count: int,
) -> ExperiencePromotionStats:
    processed = sum(outcome.processed for outcome in outcomes)
    promoted = sum(outcome.promoted for outcome in outcomes)
    rejected = sum(outcome.rejected for outcome in outcomes)
    return ExperiencePromotionStats(
        candidates=max(processed, discovery_candidates),
        promoted=promoted,
        deferred=sum(outcome.deferred for outcome in outcomes),
        skipped_duplicates=sum(outcome.skipped_duplicates for outcome in outcomes),
        rejected=rejected,
        promoted_experience_ids=[
            outcome.promoted_experience_id for outcome in outcomes if outcome.promoted_experience_id
        ],
    )


async def promote_experiences_from_episodes(
    store: Any,
    *,
    selector: SelectionProvider | None = None,
    max_selector_calls: int | None = None,
    repeated_goal_selector: Any | None = None,
    target_seed_id: str | None = None,
) -> ExperiencePromotionStats:
    """Promote active episode substrate rows through durable experience seeds."""
    active_episodes = await store.list_episodes(status="active", limit=500)
    await _hide_bad_existing_experiences(store)
    seeds, discovery_candidates = await _load_promotion_seeds(
        store,
        repeated_goal_selector=repeated_goal_selector,
        target_seed_id=target_seed_id,
    )
    existing_sets = await _existing_active_episode_member_sets(store)
    outcomes: list[SeedPromotionOutcome] = []
    limited_selector = _limit_selector_calls(selector, max_selector_calls=max_selector_calls)

    for seed in seeds:
        outcome = await _promote_single_seed(
            store,
            seed=seed,
            selector=limited_selector,
            existing_sets=existing_sets,
        )
        outcomes.append(outcome)
        if outcome.included_episode_ids:
            existing_sets.append(set(outcome.included_episode_ids))

    return _promotion_stats(
        outcomes=outcomes,
        discovery_candidates=discovery_candidates,
        active_episode_count=len(active_episodes),
    )


__all__ = ["promote_experiences_from_episodes"]
