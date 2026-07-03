"""Orchestrate all L2 experience seed discovery sources."""

from __future__ import annotations

from typing import Any

from .seed_features import _episode_features
from .seed_models import ExperienceSeedDiscoveryStats, RepeatedGoalSelector
from .seed_source_anchor import _discover_anchor_repeated_goal_seeds
from .seed_source_project import _discover_project_seeds
from .seed_source_selector import _discover_repeated_goal_seeds
from .seed_source_text import _discover_text_repeated_goal_seeds


def _merge_stats(*stats: ExperienceSeedDiscoveryStats) -> ExperienceSeedDiscoveryStats:
    return ExperienceSeedDiscoveryStats(
        candidates=sum(item.candidates for item in stats),
        created=sum(item.created for item in stats),
        skipped_duplicates=sum(item.skipped_duplicates for item in stats),
        skipped_generic=sum(item.skipped_generic for item in stats),
        created_seed_ids=[
            seed_id
            for item in stats
            for seed_id in item.created_seed_ids
        ],
    )


async def discover_experience_seeds(
    store: Any,
    *,
    repeated_goal_selector: RepeatedGoalSelector | None = None,
    limit: int = 500,
) -> ExperienceSeedDiscoveryStats:
    """Discover candidate seeds from active episode substrate."""
    episodes = await store.list_episodes(status="active", limit=limit)
    if not episodes:
        return ExperienceSeedDiscoveryStats()
    sorted_episodes = sorted(episodes, key=lambda item: float(item["time_start"]))
    features = _episode_features(sorted_episodes)
    project_stats = await _discover_project_seeds(store, sorted_episodes)
    anchor_stats = await _discover_anchor_repeated_goal_seeds(store, features)
    text_stats = await _discover_text_repeated_goal_seeds(store, features)
    repeated_stats = await _discover_repeated_goal_seeds(
        store,
        sorted_episodes,
        repeated_goal_selector,
    )
    return _merge_stats(project_stats, anchor_stats, text_stats, repeated_stats)
