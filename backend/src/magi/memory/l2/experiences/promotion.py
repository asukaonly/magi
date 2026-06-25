"""Seed-driven promotion from episode substrate to L2 experiences."""

from __future__ import annotations

import time
import uuid
from typing import Any

from .models import ExperiencePromotionStats
from .seed_discovery import discover_experience_seeds, is_generic_experience_anchor
from .seed_recall import recall_candidate_evidence_for_seed
from .seed_selection import SelectionProvider, select_experience_from_seed


DUPLICATE_OVERLAP_RATIO = 0.8
MIN_CANDIDATE_SEED_CONFIDENCE = 0.6
LEGACY_GENERIC_INTERPRETATION = (
    "magi grouped related episode evidence into a narratable memory."
)


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
    return _ordered_unique([
        value
        for value in values
        if not is_generic_experience_anchor(value)
    ])


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


async def _hide_bad_legacy_experiences(store: Any) -> int:
    hidden = 0
    for experience in await store.list_experiences(status="active", limit=500):
        if not _is_bad_legacy_experience(experience):
            continue
        updated = await store.update_experience(
            experience_id=str(experience["experience_id"]),
            status="hidden",
            last_recomputed_at=time.time(),
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
    for existing in existing_sets:
        overlap = len(candidate_ids & existing) / min(len(candidate_ids), len(existing))
        if overlap >= DUPLICATE_OVERLAP_RATIO:
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
    await store.add_experience_members(experience_id=experience_id, members=members)
    await store.recompute_experience_counts(experience_id=experience_id)
    await store.update_experience_seed(
        seed_id=str(seed["seed_id"]),
        status="promoted",
        promoted_experience_id=experience_id,
        confidence=float(selection.confidence),
        last_evaluated_at=time.time(),
    )
    return experience_id


async def promote_experiences_from_episodes(
    store: Any,
    *,
    selector: SelectionProvider | None = None,
    repeated_goal_selector: Any | None = None,
    target_seed_id: str | None = None,
) -> ExperiencePromotionStats:
    """Promote active episode substrate rows through durable experience seeds."""
    active_episodes = await store.list_episodes(status="active", limit=500)
    await _hide_bad_legacy_experiences(store)
    discovery_candidates = 0
    if target_seed_id:
        seed = await store.get_experience_seed(seed_id=target_seed_id)
        seeds = [seed] if seed is not None else []
    else:
        discovery_stats = await discover_experience_seeds(
            store,
            repeated_goal_selector=repeated_goal_selector,
        )
        discovery_candidates = discovery_stats.candidates
        seeds = await store.list_experience_seeds(statuses=["accepted", "candidate"], limit=500)
        seeds = sorted(seeds, key=_seed_processing_key)
    existing_sets = await _existing_active_episode_member_sets(store)

    processed = 0
    promoted = 0
    skipped_duplicates = 0
    rejected = 0
    promoted_experience_ids: list[str] = []

    for seed in seeds:
        if seed.get("promoted_experience_id"):
            continue
        if str(seed.get("status") or "") == "candidate" and float(seed.get("confidence") or 0.0) < MIN_CANDIDATE_SEED_CONFIDENCE:
            rejected += 1
            await store.update_experience_seed(
                seed_id=str(seed["seed_id"]),
                last_evaluated_at=time.time(),
            )
            continue

        processed += 1
        pack = await recall_candidate_evidence_for_seed(store, seed_id=str(seed["seed_id"]))
        selection = await select_experience_from_seed(
            seed=pack["seed"],
            evidence_pack=pack,
            selector=selector,
        )
        if (
            not selection.is_experience
            or not selection.included_episode_ids
            or selection.time_start is None
            or selection.time_end is None
        ):
            rejected += 1
            await store.update_experience_seed(
                seed_id=str(seed["seed_id"]),
                last_evaluated_at=time.time(),
            )
            continue

        if _is_duplicate(selection.included_episode_ids, existing_sets):
            skipped_duplicates += 1
            await store.update_experience_seed(
                seed_id=str(seed["seed_id"]),
                last_evaluated_at=time.time(),
            )
            continue

        experience_id = await _promote_seed_selection(
            store,
            seed=seed,
            selection=selection,
        )
        existing_sets.append(set(selection.included_episode_ids))
        promoted_experience_ids.append(experience_id)
        promoted += 1

    if processed == 0 and promoted == 0 and active_episodes:
        rejected += len(active_episodes)

    return ExperiencePromotionStats(
        candidates=max(processed, discovery_candidates),
        promoted=promoted,
        skipped_duplicates=skipped_duplicates,
        rejected=rejected,
        promoted_experience_ids=promoted_experience_ids,
    )


__all__ = ["promote_experiences_from_episodes"]
