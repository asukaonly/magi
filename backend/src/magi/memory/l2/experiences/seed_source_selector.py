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
        title = str(proposal.get("title") or "").strip()
        episode_ids = [
            str(item)
            for item in proposal.get("episode_ids") or []
            if str(item) in episodes_by_id
        ]
        if not title or not episode_ids:
            continue
        candidates += 1
        grouped = [episodes_by_id[episode_id] for episode_id in episode_ids]
        entity_ids = _ordered_unique(
            proposal.get("anchor_entity_ids")
            or [
                entity
                for episode in grouped
                for entity in _episode_concrete_entity_ids(episode)
            ]
        )
        place_ids = _ordered_unique(
            proposal.get("anchor_place_ids")
            or [
                place
                for episode in grouped
                for place in _episode_concrete_place_ids(episode)
            ]
        )
        topic_keys = _ordered_unique(
            proposal.get("anchor_topic_keys")
            or [
                topic
                for episode in grouped
                for topic in _episode_concrete_topic_keys(episode)
            ]
        )
        confidence = float(proposal.get("confidence") or 0.0)
        seed_id = _seed_id("repeated", f"{title}:{'|'.join(episode_ids)}")
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
            time_start=min(float(episode["time_start"]) for episode in grouped),
            time_end=max(float(episode["time_end"]) for episode in grouped),
            confidence=confidence,
            source_ref_type="repeated_goal_selector",
            source_ref_id=episode_ids[0],
            evidence_episode_ids=episode_ids,
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
