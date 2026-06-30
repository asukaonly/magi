"""Text-token repeated-goal seed discovery for L2 experiences."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _TextRepeatedGoalCandidate:
    episode_ids: tuple[str, ...]
    token: str
    features: list[_EpisodeSeedFeatures]
    score: float


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


def _group_features_by_text_token(
    features: Sequence[_EpisodeSeedFeatures],
) -> dict[str, list[_EpisodeSeedFeatures]]:
    token_groups: dict[str, list[_EpisodeSeedFeatures]] = defaultdict(list)
    for feature in features:
        for token in feature.text_tokens:
            token_groups[token].append(feature)
    return token_groups


def _candidate_from_text_run(
    token: str,
    run: list[_EpisodeSeedFeatures],
) -> _TextRepeatedGoalCandidate | None:
    if any(_project_anchor_items(feature.episode) for feature in run):
        return None
    if _token_matches_source_entity(token, run):
        return None
    if not _passes_repeated_goal_gate(run):
        return None
    episode_ids = tuple(_candidate_episode_ids(run))
    return _TextRepeatedGoalCandidate(
        episode_ids=episode_ids,
        token=token,
        features=run,
        score=float(len(token) * len(run)),
    )


def _best_text_candidates_by_episode_set(
    features: Sequence[_EpisodeSeedFeatures],
) -> dict[tuple[str, ...], _TextRepeatedGoalCandidate]:
    token_groups = _group_features_by_text_token(features)
    best_by_episode_set: dict[tuple[str, ...], _TextRepeatedGoalCandidate] = {}

    for token, grouped in token_groups.items():
        unique_by_id = {
            str(feature.episode["episode_id"]): feature
            for feature in grouped
        }
        for run in _contiguous_feature_runs(list(unique_by_id.values())):
            candidate = _candidate_from_text_run(token, run)
            if candidate is None:
                continue
            previous = best_by_episode_set.get(candidate.episode_ids)
            if previous is None or candidate.score > previous.score:
                best_by_episode_set[candidate.episode_ids] = candidate

    return best_by_episode_set


def _selection_sort_key(
    item: tuple[tuple[str, ...], _TextRepeatedGoalCandidate],
) -> tuple[int, float, float]:
    episode_ids, candidate = item
    return (
        -len(episode_ids),
        -candidate.score,
        float(candidate.features[0].episode["time_start"]),
    )


def _select_non_overlapping_text_candidates(
    best_by_episode_set: dict[tuple[str, ...], _TextRepeatedGoalCandidate],
) -> list[_TextRepeatedGoalCandidate]:
    selected_sets: list[set[str]] = []
    selected_candidates: list[_TextRepeatedGoalCandidate] = []
    for item in sorted(best_by_episode_set.items(), key=_selection_sort_key):
        episode_ids, candidate = item
        if _overlaps_selected_episode_set(episode_ids, selected_sets):
            continue
        selected_sets.append(set(episode_ids))
        selected_candidates.append(candidate)
    return selected_candidates


def _write_sort_key(
    candidate: _TextRepeatedGoalCandidate,
) -> tuple[float, tuple[str, ...]]:
    return (
        float(candidate.features[0].episode["time_start"]),
        candidate.episode_ids,
    )


async def _write_text_repeated_goal_candidates(
    store: Any,
    selected_candidates: Sequence[_TextRepeatedGoalCandidate],
) -> ExperienceSeedDiscoveryStats:
    candidates = 0
    created = 0
    skipped_duplicates = 0
    created_seed_ids: list[str] = []

    for candidate in sorted(selected_candidates, key=_write_sort_key):
        candidates += 1
        title = _readable_text_token(candidate.token)
        if not title:
            continue
        seed_id = _seed_id(
            "repeated",
            f"text:{candidate.token}:{'|'.join(candidate.episode_ids)}",
        )
        was_created, _ = await _create_repeated_seed_from_features(
            store,
            seed_id=seed_id,
            title=title,
            description=f"这些片段在一段连续时间里反复围绕「{title}」展开。",
            features=candidate.features,
            anchor_topic_keys=[candidate.token],
            confidence=_repeated_goal_confidence(
                candidate.features,
                token=candidate.token,
            ),
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


async def _discover_text_repeated_goal_seeds(
    store: Any,
    features: Sequence[_EpisodeSeedFeatures],
) -> ExperienceSeedDiscoveryStats:
    best_by_episode_set = _best_text_candidates_by_episode_set(features)
    selected_candidates = _select_non_overlapping_text_candidates(best_by_episode_set)
    return await _write_text_repeated_goal_candidates(store, selected_candidates)
