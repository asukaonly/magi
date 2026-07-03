"""Episode feature extraction for L2 experience seed discovery."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from ..storage.utils import _l2_setting
from .seed_anchors import (
    _episode_concrete_entity_ids,
    _episode_concrete_place_ids,
    _episode_concrete_topic_keys,
    _ordered_unique,
    _text_tokens,
)
from .seed_models import _EpisodeSeedFeatures


QUOTE_PATTERN = re.compile(r"[「“\"]([^」”\"]{2,40})[」”\"]")
MAX_REPEATED_GOAL_WINDOW_SECONDS = 30 * 24 * 60 * 60
MAX_REPEATED_GOAL_GAP_SECONDS = 7 * 24 * 60 * 60
MIN_REPEATED_GOAL_EPISODES = 3
MIN_REPEATED_GOAL_EVENTS = 8


def _episode_summary_terms(episode: Mapping[str, Any]) -> list[str]:
    """High-signal text terms from the episode's back-written label/summary.

    The L3 episodic summary label/content are back-written onto the episode
    row during consolidation, so seed discovery can read them locally instead
    of querying the L3 summaries table across layers. Only the concise label
    and quoted phrases are used — whole summary prose would dilute the
    clustering tokens.
    """
    label = str(episode.get("label") or "").strip()
    summary = str(episode.get("summary") or "").strip()
    terms: list[str] = []
    if label:
        terms.append(label)
    terms.extend(match.strip() for match in QUOTE_PATTERN.findall(summary))
    return _ordered_unique(terms)


def _episode_seed_text(episode: Mapping[str, Any]) -> str:
    parts = [
        episode.get("user_label"),
        "\n".join(_episode_summary_terms(episode)),
    ]
    return "\n".join(str(part).strip() for part in parts if str(part or "").strip())


def _episode_features(
    episodes: Sequence[dict[str, Any]],
) -> list[_EpisodeSeedFeatures]:
    features: list[_EpisodeSeedFeatures] = []
    for episode in episodes:
        text = _episode_seed_text(episode)
        features.append(
            _EpisodeSeedFeatures(
                episode=episode,
                text=text,
                entity_ids=_episode_concrete_entity_ids(episode),
                place_ids=_episode_concrete_place_ids(episode),
                topic_keys=_episode_concrete_topic_keys(episode),
                text_tokens=_text_tokens(text),
            )
        )
    return features


def _total_source_events(features: Sequence[_EpisodeSeedFeatures]) -> int:
    return sum(int(item.episode.get("source_event_count") or 0) for item in features)


def _time_bounds(features: Sequence[_EpisodeSeedFeatures]) -> tuple[float, float]:
    return (
        min(float(item.episode["time_start"]) for item in features),
        max(float(item.episode["time_end"]) for item in features),
    )


def _passes_repeated_goal_gate(features: Sequence[_EpisodeSeedFeatures]) -> bool:
    min_episodes = int(_l2_setting("experience", "min_repeated_goal_episodes", MIN_REPEATED_GOAL_EPISODES))
    min_events = int(_l2_setting("experience", "min_repeated_goal_events", MIN_REPEATED_GOAL_EVENTS))
    max_window = float(
        _l2_setting("experience", "max_repeated_goal_window_seconds", MAX_REPEATED_GOAL_WINDOW_SECONDS)
    )
    max_gap = float(
        _l2_setting("experience", "max_repeated_goal_gap_seconds", MAX_REPEATED_GOAL_GAP_SECONDS)
    )
    if len(features) < min_episodes:
        return False
    if _total_source_events(features) < min_events:
        return False
    ordered = sorted(features, key=lambda item: float(item.episode["time_start"]))
    start, end = _time_bounds(ordered)
    if end - start > max_window:
        return False
    for left, right in zip(ordered, ordered[1:]):
        gap = float(right.episode["time_start"]) - float(left.episode["time_end"])
        if gap > max_gap:
            return False
    return True


def _repeated_goal_confidence(
    features: Sequence[_EpisodeSeedFeatures],
    *,
    token: str = "",
) -> float:
    base = 0.56 + 0.06 * min(len(features), 4)
    event_bonus = min(0.08, _total_source_events(features) / 200.0)
    token_bonus = min(0.06, len(token) / 100.0)
    return min(0.88, base + event_bonus + token_bonus)


def _candidate_episode_ids(features: Sequence[_EpisodeSeedFeatures]) -> list[str]:
    return [
        str(item.episode["episode_id"])
        for item in sorted(features, key=lambda feature: float(feature.episode["time_start"]))
    ]


def _contiguous_feature_runs(
    features: Sequence[_EpisodeSeedFeatures],
) -> list[list[_EpisodeSeedFeatures]]:
    ordered = sorted(features, key=lambda item: float(item.episode["time_start"]))
    runs: list[list[_EpisodeSeedFeatures]] = []
    current: list[_EpisodeSeedFeatures] = []
    max_gap = float(
        _l2_setting("experience", "max_repeated_goal_gap_seconds", MAX_REPEATED_GOAL_GAP_SECONDS)
    )
    for feature in ordered:
        if not current:
            current = [feature]
            continue
        gap = float(feature.episode["time_start"]) - float(current[-1].episode["time_end"])
        if gap > max_gap:
            runs.append(current)
            current = [feature]
        else:
            current.append(feature)
    if current:
        runs.append(current)
    return runs
