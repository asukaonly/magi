"""Deterministic promotion from episode substrate to L2 experiences."""

from __future__ import annotations

import uuid
import re
from dataclasses import dataclass
from typing import Any

from .models import ExperiencePromotionStats


SINGLE_STRONG_MIN_EVENTS = 20
SINGLE_STRONG_MIN_DURATION_SECONDS = 45 * 60
GROUP_MIN_EVENTS = 10
GROUP_MAX_GAP_SECONDS = 2 * 60 * 60
DUPLICATE_OVERLAP_RATIO = 0.8
PLACEHOLDER_TITLES = {
    "untitled",
    "untitled episode",
    "untitled experience",
    "experience",
}
MACHINE_ID_PATTERN = re.compile(r"^(?:[0-9a-f]{10,}|[0-9A-HJKMNP-TV-Z]{12,})$", re.IGNORECASE)
LOW_VALUE_LABELS = {
    "local_user",
    "local user",
    "self",
    "user",
    "user self",
}


@dataclass(frozen=True)
class _ExperienceCandidate:
    episode_ids: list[str]
    title: str
    time_start: float
    time_end: float
    primary_entity_ids: list[str]
    primary_place_ids: list[str]
    primary_topic_keys: list[str]
    source_event_count: int
    narrative_score: float


def _ordered_unique(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _is_placeholder_title(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered in PLACEHOLDER_TITLES or lowered.startswith("untitled exper")


def _format_theme_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if ":" in text:
        _, _, text = text.partition(":")
    raw_text = text.strip()
    text = raw_text.replace("_", " ").replace("-", " ")
    normalized = text.casefold()
    if (
        not text
        or _is_placeholder_title(text)
        or raw_text.isdigit()
        or MACHINE_ID_PATTERN.fullmatch(raw_text)
        or normalized in LOW_VALUE_LABELS
    ):
        return ""
    return text


def _episode_explicit_title(episode: dict[str, Any]) -> str:
    for key in ("user_label", "label", "summary"):
        value = str(episode.get(key) or "").strip()
        if value and not _is_placeholder_title(value):
            return value
    return ""


def _episode_theme_labels(episode: dict[str, Any]) -> list[str]:
    return _ordered_unique([
        _format_theme_label(value)
        for key in ("primary_entity_ids", "primary_place_ids", "primary_topic_keys")
        for value in (episode.get(key) or [])
    ])


def _candidate_title(episodes: list[dict[str, Any]]) -> str:
    explicit_titles = _ordered_unique([
        title
        for episode in episodes
        if (title := _episode_explicit_title(episode))
    ])
    if explicit_titles:
        return explicit_titles[0] if len(explicit_titles) == 1 else " / ".join(explicit_titles[:2])

    theme_labels = _ordered_unique([
        label
        for episode in episodes
        for label in _episode_theme_labels(episode)
    ])
    if theme_labels:
        return " / ".join(theme_labels[:3])
    return "Experience"


def _shares_theme(a: dict[str, Any], b: dict[str, Any]) -> bool:
    entity_overlap = set(a.get("primary_entity_ids") or []) & set(b.get("primary_entity_ids") or [])
    topic_overlap = set(a.get("primary_topic_keys") or []) & set(b.get("primary_topic_keys") or [])
    place_overlap = set(a.get("primary_place_ids") or []) & set(b.get("primary_place_ids") or [])
    return bool(entity_overlap or topic_overlap or place_overlap)


def _has_theme(episode: dict[str, Any]) -> bool:
    return bool(
        episode.get("primary_entity_ids")
        or episode.get("primary_topic_keys")
        or episode.get("primary_place_ids")
    )


async def _episode_event_count(store: Any, episode: dict[str, Any]) -> int:
    count = await store.count_episode_events(episode_id=str(episode["episode_id"]))
    if count > 0:
        return count
    return int(episode.get("source_event_count") or 0)


async def _candidate_from_episodes(
    store: Any,
    episodes: list[dict[str, Any]],
) -> _ExperienceCandidate:
    event_counts = [await _episode_event_count(store, episode) for episode in episodes]
    total_events = sum(event_counts)
    title = _candidate_title(episodes)
    entity_ids = _ordered_unique([
        entity
        for episode in episodes
        for entity in (episode.get("primary_entity_ids") or [])
    ])
    place_ids = _ordered_unique([
        place
        for episode in episodes
        for place in (episode.get("primary_place_ids") or [])
    ])
    topic_keys = _ordered_unique([
        topic
        for episode in episodes
        for topic in (episode.get("primary_topic_keys") or [])
    ])
    duration = max(float(episode["time_end"]) for episode in episodes) - min(
        float(episode["time_start"]) for episode in episodes
    )
    score = _score_candidate(
        episode_count=len(episodes),
        event_count=total_events,
        duration=duration,
        theme_count=len(entity_ids) + len(place_ids) + len(topic_keys),
    )
    return _ExperienceCandidate(
        episode_ids=[str(episode["episode_id"]) for episode in episodes],
        title=title,
        time_start=min(float(episode["time_start"]) for episode in episodes),
        time_end=max(float(episode["time_end"]) for episode in episodes),
        primary_entity_ids=entity_ids,
        primary_place_ids=place_ids,
        primary_topic_keys=topic_keys,
        source_event_count=total_events,
        narrative_score=score,
    )


def _score_candidate(
    *,
    episode_count: int,
    event_count: int,
    duration: float,
    theme_count: int,
) -> float:
    event_score = min(event_count / 30.0, 1.0) * 0.36
    duration_score = min(duration / (2 * 60 * 60), 1.0) * 0.24
    theme_score = min(theme_count / 3.0, 1.0) * 0.24
    continuity_score = min(episode_count / 2.0, 1.0) * 0.16
    return round(event_score + duration_score + theme_score + continuity_score, 3)


async def _single_episode_candidate(store: Any, episode: dict[str, Any]) -> _ExperienceCandidate | None:
    event_count = await _episode_event_count(store, episode)
    duration = float(episode["time_end"]) - float(episode["time_start"])
    if event_count < SINGLE_STRONG_MIN_EVENTS:
        return None
    if duration < SINGLE_STRONG_MIN_DURATION_SECONDS and event_count < SINGLE_STRONG_MIN_EVENTS:
        return None
    if not _has_theme(episode):
        return None
    return await _candidate_from_episodes(store, [episode])


async def _adjacent_group_candidates(
    store: Any,
    episodes: list[dict[str, Any]],
) -> list[_ExperienceCandidate]:
    candidates: list[_ExperienceCandidate] = []
    current: list[dict[str, Any]] = []
    current_events = 0

    for episode in episodes:
        event_count = await _episode_event_count(store, episode)
        if not current:
            current = [episode]
            current_events = event_count
            continue

        previous = current[-1]
        gap = float(episode["time_start"]) - float(previous["time_end"])
        if gap <= GROUP_MAX_GAP_SECONDS and _shares_theme(previous, episode):
            current.append(episode)
            current_events += event_count
            continue

        if len(current) >= 2 and current_events >= GROUP_MIN_EVENTS:
            candidates.append(await _candidate_from_episodes(store, current))
        current = [episode]
        current_events = event_count

    if len(current) >= 2 and current_events >= GROUP_MIN_EVENTS:
        candidates.append(await _candidate_from_episodes(store, current))
    return candidates


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


def _is_duplicate(candidate: _ExperienceCandidate, existing_sets: list[set[str]]) -> bool:
    candidate_ids = set(candidate.episode_ids)
    if not candidate_ids:
        return False
    for existing in existing_sets:
        overlap = len(candidate_ids & existing) / min(len(candidate_ids), len(existing))
        if overlap >= DUPLICATE_OVERLAP_RATIO:
            return True
    return False


async def _promote_candidate(store: Any, candidate: _ExperienceCandidate) -> str:
    experience_id = str(uuid.uuid4())
    await store.create_experience(
        experience_id=experience_id,
        status="active",
        title=candidate.title,
        time_start=candidate.time_start,
        time_end=candidate.time_end,
        intent=candidate.title,
        magi_interpretation=(
            "Magi grouped related episode evidence into a narratable memory."
        ),
        narrative_score=candidate.narrative_score,
        primary_entity_ids=candidate.primary_entity_ids,
        primary_place_ids=candidate.primary_place_ids,
        primary_topic_keys=candidate.primary_topic_keys,
        source_episode_count=len(candidate.episode_ids),
        source_event_count=candidate.source_event_count,
    )
    await store.add_experience_members(
        experience_id=experience_id,
        members=[
            {
                "member_type": "episode",
                "member_id": episode_id,
                "role": "core",
                "confidence": candidate.narrative_score,
            }
            for episode_id in candidate.episode_ids
        ],
    )
    await store.recompute_experience_counts(experience_id=experience_id)
    return experience_id


async def promote_experiences_from_episodes(store: Any) -> ExperiencePromotionStats:
    """Promote active episode substrate rows into product-grade experiences."""
    episodes = await store.list_episodes(status="active", limit=500)
    if not episodes:
        return ExperiencePromotionStats()

    sorted_episodes = sorted(episodes, key=lambda item: float(item["time_start"]))
    group_candidates = await _adjacent_group_candidates(store, sorted_episodes)
    grouped_episode_ids = {
        episode_id
        for candidate in group_candidates
        for episode_id in candidate.episode_ids
    }
    single_candidates: list[_ExperienceCandidate] = []
    for episode in sorted_episodes:
        if str(episode["episode_id"]) in grouped_episode_ids:
            continue
        candidate = await _single_episode_candidate(store, episode)
        if candidate is not None:
            single_candidates.append(candidate)

    candidates = group_candidates + single_candidates
    existing_sets = await _existing_active_episode_member_sets(store)
    promoted = 0
    skipped_duplicates = 0
    promoted_experience_ids: list[str] = []

    for candidate in candidates:
        if _is_duplicate(candidate, existing_sets):
            skipped_duplicates += 1
            continue
        experience_id = await _promote_candidate(store, candidate)
        existing_sets.append(set(candidate.episode_ids))
        promoted_experience_ids.append(experience_id)
        promoted += 1

    rejected = max(0, len(sorted_episodes) - len(grouped_episode_ids) - len(single_candidates))
    return ExperiencePromotionStats(
        candidates=len(candidates),
        promoted=promoted,
        skipped_duplicates=skipped_duplicates,
        rejected=rejected,
        promoted_experience_ids=promoted_experience_ids,
    )


__all__ = ["promote_experiences_from_episodes"]
