"""Text-token repeated-goal seed discovery for L2 experiences."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Sequence

from .seed_anchors import (
    _project_anchor_items,
    _readable_text_token,
    _seed_id,
    _token_matches_source_entity,
)
from .seed_features import (
    _candidate_episode_ids,
    _contiguous_feature_runs,
    _passes_repeated_goal_gate,
    _repeated_goal_confidence,
)
from .seed_models import ExperienceSeedDiscoveryStats, _EpisodeSeedFeatures
from .seed_writes import _create_repeated_seed_from_features


def _overlaps_selected_episode_set(
    episode_ids: tuple[str, ...],
    selected_sets: Sequence[set[str]],
) -> bool:
    current = set(episode_ids)
    for selected in selected_sets:
        overlap = len(current & selected)
        if overlap and overlap / min(len(current), len(selected)) >= 0.66:
            return True
    return False


async def _discover_text_repeated_goal_seeds(
    store: Any,
    features: Sequence[_EpisodeSeedFeatures],
) -> ExperienceSeedDiscoveryStats:
    token_groups: dict[str, list[_EpisodeSeedFeatures]] = defaultdict(list)
    for feature in features:
        for token in feature.text_tokens:
            token_groups[token].append(feature)

    best_by_episode_set: dict[tuple[str, ...], tuple[str, list[_EpisodeSeedFeatures], float]] = {}
    for token, grouped in token_groups.items():
        unique_by_id = {
            str(feature.episode["episode_id"]): feature
            for feature in grouped
        }
        for run in _contiguous_feature_runs(list(unique_by_id.values())):
            if any(_project_anchor_items(feature.episode) for feature in run):
                continue
            if _token_matches_source_entity(token, run):
                continue
            if not _passes_repeated_goal_gate(run):
                continue
            episode_ids = tuple(_candidate_episode_ids(run))
            score = len(token) * len(run)
            previous = best_by_episode_set.get(episode_ids)
            if previous is None or score > previous[2]:
                best_by_episode_set[episode_ids] = (token, run, float(score))

    selected_sets: list[set[str]] = []
    selected_candidates: list[
        tuple[tuple[str, ...], tuple[str, list[_EpisodeSeedFeatures], float]]
    ] = []
    for item in sorted(
        best_by_episode_set.items(),
        key=lambda item: (-len(item[0]), -item[1][2], float(item[1][1][0].episode["time_start"])),
    ):
        episode_ids, candidate = item
        if _overlaps_selected_episode_set(episode_ids, selected_sets):
            continue
        selected_sets.append(set(episode_ids))
        selected_candidates.append(item)

    candidates = 0
    created = 0
    skipped_duplicates = 0
    created_seed_ids: list[str] = []
    for episode_ids, (token, grouped, _) in sorted(
        selected_candidates,
        key=lambda item: (float(item[1][1][0].episode["time_start"]), item[0]),
    ):
        candidates += 1
        title = _readable_text_token(token)
        if not title:
            continue
        seed_id = _seed_id("repeated", f"text:{token}:{'|'.join(episode_ids)}")
        was_created, _ = await _create_repeated_seed_from_features(
            store,
            seed_id=seed_id,
            title=title,
            description=f"这些片段在一段连续时间里反复围绕「{title}」展开。",
            features=grouped,
            anchor_topic_keys=[token],
            confidence=_repeated_goal_confidence(grouped, token=token),
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
