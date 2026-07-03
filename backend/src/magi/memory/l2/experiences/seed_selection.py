"""Select coherent experience evidence from a recalled seed pack."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Sequence

from .seed_discovery import is_generic_experience_anchor


SelectionProvider = Callable[
    [dict[str, Any], dict[str, Any]],
    Mapping[str, Any] | Awaitable[Mapping[str, Any]],
]


@dataclass(frozen=True)
class ExperienceSeedSelection:
    """Normalized selection result for seed-driven promotion."""

    is_experience: bool
    title: str
    one_sentence_review: str
    included_episode_ids: list[str] = field(default_factory=list)
    included_event_ids: list[str] = field(default_factory=list)
    excluded_refs: list[dict[str, str]] = field(default_factory=list)
    time_start: float | None = None
    time_end: float | None = None
    confidence: float = 0.0
    reason: str = ""
    primary_entity_ids: list[str] = field(default_factory=list)
    primary_place_ids: list[str] = field(default_factory=list)
    primary_topic_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _DefaultSelectionContext:
    seed_entities: set[str]
    seed_places: set[str]
    seed_topics: set[str]
    seed_type: str
    trigger_ids: set[Any]
    evidence_episode_ids: set[str]
    candidate_episodes: list[dict[str, Any]]

    @property
    def has_concrete_anchor(self) -> bool:
        return bool(self.seed_entities or self.seed_places or self.seed_topics)


def _ordered_unique(values: Sequence[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _concrete(values: Sequence[Any]) -> list[str]:
    return _ordered_unique([
        value
        for value in values
        if not is_generic_experience_anchor(value)
    ])


def _seed_anchor_sets(seed: Mapping[str, Any]) -> tuple[set[str], set[str], set[str]]:
    return (
        set(_concrete(seed.get("anchor_entity_ids") or [])),
        set(_concrete(seed.get("anchor_place_ids") or [])),
        set(_concrete(seed.get("anchor_topic_keys") or [])),
    )


def _episode_shares_seed_anchor(
    episode: Mapping[str, Any],
    *,
    seed_entities: set[str],
    seed_places: set[str],
    seed_topics: set[str],
) -> bool:
    episode_entities = set(_concrete(episode.get("primary_entity_ids") or []))
    episode_places = set(_concrete(episode.get("primary_place_ids") or []))
    episode_topics = set(_concrete(episode.get("primary_topic_keys") or []))
    return bool(
        episode_entities & seed_entities
        or episode_places & seed_places
        or episode_topics & seed_topics
    )


def _selection_episode_fields(
    episodes: list[dict[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    return (
        _ordered_unique([
            entity
            for episode in episodes
            for entity in _concrete(episode.get("primary_entity_ids") or [])
        ]),
        _ordered_unique([
            place
            for episode in episodes
            for place in _concrete(episode.get("primary_place_ids") or [])
        ]),
        _ordered_unique([
            topic
            for episode in episodes
            for topic in _concrete(episode.get("primary_topic_keys") or [])
        ]),
    )


def _review(seed: Mapping[str, Any], title: str) -> str:
    description = str(seed.get("description") or "").strip()
    if description:
        return description
    return f"Magi 看到这段经历主要围绕「{title}」展开。"


def _normalize_selector_result(result: Mapping[str, Any]) -> ExperienceSeedSelection:
    return ExperienceSeedSelection(
        is_experience=bool(result.get("is_experience")),
        title=str(result.get("title") or "").strip(),
        one_sentence_review=str(result.get("one_sentence_review") or "").strip(),
        included_episode_ids=_ordered_unique(result.get("included_episode_ids") or []),
        included_event_ids=_ordered_unique(result.get("included_event_ids") or []),
        excluded_refs=[
            {
                "ref_type": str(item.get("ref_type") or ""),
                "ref_id": str(item.get("ref_id") or ""),
                "reason": str(item.get("reason") or ""),
            }
            for item in (result.get("excluded_refs") or [])
            if isinstance(item, Mapping)
        ],
        time_start=(
            float(result["time_start"]) if result.get("time_start") is not None else None
        ),
        time_end=float(result["time_end"]) if result.get("time_end") is not None else None,
        confidence=float(result.get("confidence") or 0.0),
        reason=str(result.get("reason") or "").strip(),
        primary_entity_ids=_ordered_unique(result.get("primary_entity_ids") or []),
        primary_place_ids=_ordered_unique(result.get("primary_place_ids") or []),
        primary_topic_keys=_ordered_unique(result.get("primary_topic_keys") or []),
    )


async def _selector_result(
    selector: SelectionProvider,
    *,
    seed: dict[str, Any],
    evidence_pack: dict[str, Any],
) -> ExperienceSeedSelection:
    result = selector(seed, evidence_pack)
    if inspect.isawaitable(result):
        result = await result
    return _normalize_selector_result(result)


def _default_selection(seed: dict[str, Any], evidence_pack: dict[str, Any]) -> ExperienceSeedSelection:
    context = _default_selection_context(seed, evidence_pack)
    if not context.has_concrete_anchor:
        return ExperienceSeedSelection(
            is_experience=False,
            title=str(seed.get("title") or ""),
            one_sentence_review="",
            reason="Seed has no concrete anchors.",
        )

    included = _matching_seed_episodes(context)
    if not included:
        return ExperienceSeedSelection(
            is_experience=False,
            title=str(seed.get("title") or ""),
            one_sentence_review="",
            reason="No candidate episodes matched the seed anchors.",
        )

    return _build_default_selection(seed, context, included)


def _default_selection_context(
    seed: dict[str, Any],
    evidence_pack: dict[str, Any],
) -> _DefaultSelectionContext:
    seed_entities, seed_places, seed_topics = _seed_anchor_sets(seed)
    evidence_episode_ids = {
        str(item.get("ref_id") or "")
        for item in (evidence_pack.get("seed_evidence") or [])
        if isinstance(item, Mapping)
        and str(item.get("ref_type") or "") == "episode"
        and str(item.get("role") or "") in {"trigger", "support"}
    }
    return _DefaultSelectionContext(
        seed_entities=seed_entities,
        seed_places=seed_places,
        seed_topics=seed_topics,
        seed_type=str(seed.get("seed_type") or ""),
        trigger_ids=set(evidence_pack.get("trigger_episode_ids") or []),
        evidence_episode_ids=evidence_episode_ids,
        candidate_episodes=list(evidence_pack.get("candidate_episodes") or []),
    )


def _matching_seed_episodes(context: _DefaultSelectionContext) -> list[dict[str, Any]]:
    return [
        episode
        for episode in context.candidate_episodes
        if str(episode["episode_id"]) in context.trigger_ids
        or (
            context.seed_type == "repeated_goal"
            and str(episode["episode_id"]) in context.evidence_episode_ids
        )
        or _episode_shares_seed_anchor(
            episode,
            seed_entities=context.seed_entities,
            seed_places=context.seed_places,
            seed_topics=context.seed_topics,
        )
    ]


def _build_default_selection(
    seed: dict[str, Any],
    context: _DefaultSelectionContext,
    included: list[dict[str, Any]],
) -> ExperienceSeedSelection:
    included_ids = [str(episode["episode_id"]) for episode in included]
    confidence = float(seed.get("confidence") or 0.0)
    is_accepted = str(seed.get("status") or "") == "accepted"
    is_experience = is_accepted or (confidence >= 0.6 and len(included) >= 2)
    title = str(seed.get("title") or "").strip() or str(included[0].get("label") or "Experience")
    entity_ids, place_ids, topic_keys = _selection_episode_fields(included)
    return ExperienceSeedSelection(
        is_experience=is_experience,
        title=title,
        one_sentence_review=_review(seed, title) if is_experience else "",
        included_episode_ids=included_ids if is_experience else [],
        included_event_ids=[],
        excluded_refs=[
            {
                "ref_type": "episode",
                "ref_id": str(episode["episode_id"]),
                "reason": "Does not match the seed anchors.",
            }
            for episode in context.candidate_episodes
            if str(episode["episode_id"]) not in included_ids
        ],
        time_start=min(float(episode["time_start"]) for episode in included),
        time_end=max(float(episode["time_end"]) for episode in included),
        confidence=max(confidence, 0.75 if is_accepted else confidence),
        reason="Selected episodes share concrete seed anchors.",
        primary_entity_ids=entity_ids,
        primary_place_ids=place_ids,
        primary_topic_keys=topic_keys,
    )


async def select_experience_from_seed(
    *,
    seed: dict[str, Any],
    evidence_pack: dict[str, Any],
    selector: SelectionProvider | None = None,
) -> ExperienceSeedSelection:
    """Select the evidence that actually belongs to a seed."""
    if selector is not None:
        selection = await _selector_result(selector, seed=seed, evidence_pack=evidence_pack)
        if selection.title and selection.one_sentence_review:
            return selection
        if not selection.is_experience and selection.reason:
            return selection
    return _default_selection(seed, evidence_pack)


__all__ = [
    "ExperienceSeedSelection",
    "SelectionProvider",
    "select_experience_from_seed",
]
