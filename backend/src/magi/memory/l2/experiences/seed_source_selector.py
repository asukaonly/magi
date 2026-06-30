"""Selector-provided repeated-goal seed discovery for L2 experiences."""

from __future__ import annotations

import inspect
from typing import Any, Mapping, Sequence

from .seed_anchors import (
    _episode_concrete_entity_ids,
    _episode_concrete_place_ids,
    _episode_concrete_topic_keys,
    _ordered_unique,
    _seed_id,
)
from .seed_models import ExperienceSeedDiscoveryStats, RepeatedGoalSelector
from .seed_writes import _create_seed_if_missing


async def _selector_proposals(
    selector: RepeatedGoalSelector | None,
    episodes: Sequence[dict[str, Any]],
) -> Sequence[Mapping[str, Any]]:
    if selector is None:
        return []
    proposals = selector(episodes)
    if inspect.isawaitable(proposals):
        proposals = await proposals
    return proposals or []


async def _discover_repeated_goal_seeds(
    store: Any,
    episodes: Sequence[dict[str, Any]],
    selector: RepeatedGoalSelector | None,
) -> ExperienceSeedDiscoveryStats:
    proposals = await _selector_proposals(selector, episodes)
    episodes_by_id = {str(episode["episode_id"]): episode for episode in episodes}
    candidates = 0
    created = 0
    skipped_duplicates = 0
    created_seed_ids: list[str] = []

    for proposal in proposals:
        proposal_context = _proposal_context(proposal, episodes_by_id)
        if proposal_context is None:
            continue
        candidates += 1
        title, episode_ids, grouped = proposal_context
        seed_id = _seed_id("repeated", f"{title}:{'|'.join(episode_ids)}")
        was_created = await _write_repeated_goal_seed(
            store,
            proposal=proposal,
            title=title,
            seed_id=seed_id,
            episode_ids=episode_ids,
            grouped_episodes=grouped,
        )
        if was_created:
            created += 1
            created_seed_ids.append(seed_id)
        else:
            skipped_duplicates += 1

    return ExperienceSeedDiscoveryStats(
        candidates=candidates,
        created=created,
        skipped_duplicates=skipped_duplicates,
        created_seed_ids=created_seed_ids,
    )


def _proposal_context(
    proposal: Mapping[str, Any],
    episodes_by_id: dict[str, dict[str, Any]],
) -> tuple[str, list[str], list[dict[str, Any]]] | None:
    title = str(proposal.get("title") or "").strip()
    episode_ids = [
        str(item) for item in proposal.get("episode_ids") or [] if str(item) in episodes_by_id
    ]
    if not title or not episode_ids:
        return None
    return title, episode_ids, [episodes_by_id[episode_id] for episode_id in episode_ids]


async def _write_repeated_goal_seed(
    store: Any,
    *,
    proposal: Mapping[str, Any],
    title: str,
    seed_id: str,
    episode_ids: list[str],
    grouped_episodes: list[dict[str, Any]],
) -> bool:
    entity_ids, place_ids, topic_keys = _proposal_anchor_ids(proposal, grouped_episodes)
    time_start, time_end = _proposal_time_window(grouped_episodes)
    was_created, _ = await _create_seed_if_missing(
        store,
        seed_id=seed_id,
        seed_type="repeated_goal",
        status="candidate",
        title=title,
        description=str(proposal.get("description") or "").strip() or None,
        anchor_entity_ids=entity_ids,
        anchor_place_ids=place_ids,
        anchor_topic_keys=topic_keys,
        time_start=time_start,
        time_end=time_end,
        confidence=float(proposal.get("confidence") or 0.0),
        source_ref_type="repeated_goal_selector",
        source_ref_id=episode_ids[0],
        evidence_episode_ids=episode_ids,
    )
    return was_created


def _proposal_anchor_ids(
    proposal: Mapping[str, Any],
    grouped_episodes: list[dict[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    return (
        _ordered_unique(
            proposal.get("anchor_entity_ids")
            or [
                entity
                for episode in grouped_episodes
                for entity in _episode_concrete_entity_ids(episode)
            ]
        ),
        _ordered_unique(
            proposal.get("anchor_place_ids")
            or [
                place
                for episode in grouped_episodes
                for place in _episode_concrete_place_ids(episode)
            ]
        ),
        _ordered_unique(
            proposal.get("anchor_topic_keys")
            or [
                topic
                for episode in grouped_episodes
                for topic in _episode_concrete_topic_keys(episode)
            ]
        ),
    )


def _proposal_time_window(grouped_episodes: list[dict[str, Any]]) -> tuple[float, float]:
    return (
        min(float(episode["time_start"]) for episode in grouped_episodes),
        max(float(episode["time_end"]) for episode in grouped_episodes),
    )
