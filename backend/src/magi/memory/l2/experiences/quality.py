"""Quality gate for promoting candidate seeds into user-facing experiences."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .seed_discovery import (
    is_generic_experience_anchor,
    is_technical_artifact_experience_token,
)
from .seed_selection import ExperienceSeedSelection


MIN_EXPERIENCE_QUALITY_SCORE = 6

_ACTION_TERMS = {
    "adjust",
    "book",
    "build",
    "compare",
    "debug",
    "decide",
    "design",
    "edit",
    "fix",
    "implement",
    "inspect",
    "learn",
    "plan",
    "prepare",
    "read",
    "research",
    "run",
    "search",
    "test",
    "travel",
    "troubleshoot",
    "write",
    "查看",
    "修改",
    "写",
    "准备",
    "决定",
    "出发",
    "到达",
    "实现",
    "对比",
    "搜索",
    "整理",
    "旅行",
    "查",
    "测试",
    "浏览",
    "研究",
    "规划",
    "记录",
    "调试",
    "预订",
}

_PROCESS_TERMS = {
    "again",
    "after",
    "before",
    "continue",
    "continued",
    "finally",
    "later",
    "next",
    "then",
    "再次",
    "之后",
    "前",
    "后来",
    "回程",
    "最终",
    "继续",
    "随后",
}

_RECALL_ANCHOR_PREFIXES = (
    "place:",
    "project:",
    "travel:",
)


@dataclass(frozen=True)
class ExperienceQualityDecision:
    """Result of deciding whether a selected seed is experience-grade."""

    accepted: bool
    score: int
    reason: str
    components: dict[str, int] = field(default_factory=dict)


def _ordered_texts(values: Sequence[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _concrete(values: Sequence[Any]) -> list[str]:
    return _ordered_texts([
        value
        for value in values
        if not is_generic_experience_anchor(value)
        and not is_technical_artifact_experience_token(value)
    ])


def _included_episodes(
    selection: ExperienceSeedSelection,
    evidence_pack: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    included = set(selection.included_episode_ids)
    return [
        episode
        for episode in (evidence_pack.get("candidate_episodes") or [])
        if isinstance(episode, Mapping) and str(episode.get("episode_id") or "") in included
    ]


def _text_blob(
    seed: Mapping[str, Any],
    selection: ExperienceSeedSelection,
    episodes: Sequence[Mapping[str, Any]],
) -> str:
    values: list[Any] = [
        seed.get("title"),
        seed.get("description"),
        selection.title,
        selection.one_sentence_review,
    ]
    for episode in episodes:
        values.extend([
            episode.get("user_label"),
            episode.get("label"),
            episode.get("summary"),
        ])
    return "\n".join(_ordered_texts(values)).casefold()


def _all_selection_anchors(
    seed: Mapping[str, Any],
    selection: ExperienceSeedSelection,
    episodes: Sequence[Mapping[str, Any]],
) -> list[str]:
    values: list[Any] = []
    values.extend(seed.get("anchor_entity_ids") or [])
    values.extend(seed.get("anchor_place_ids") or [])
    values.extend(seed.get("anchor_topic_keys") or [])
    values.extend(selection.primary_entity_ids)
    values.extend(selection.primary_place_ids)
    values.extend(selection.primary_topic_keys)
    for episode in episodes:
        values.extend(episode.get("primary_entity_ids") or [])
        values.extend(episode.get("primary_place_ids") or [])
        values.extend(episode.get("primary_topic_keys") or [])
    return _ordered_texts(values)


def _has_term(text: str, terms: set[str]) -> bool:
    return any(term.casefold() in text for term in terms)


def _artifact_reason(
    seed: Mapping[str, Any],
    selection: ExperienceSeedSelection,
    episodes: Sequence[Mapping[str, Any]],
) -> str | None:
    values: list[Any] = [
        seed.get("title"),
        seed.get("description"),
        selection.title,
        selection.one_sentence_review,
    ]
    values.extend(selection.primary_entity_ids)
    values.extend(selection.primary_place_ids)
    values.extend(selection.primary_topic_keys)
    for episode in episodes:
        values.extend([
            episode.get("label"),
            episode.get("summary"),
            episode.get("user_label"),
            *(episode.get("primary_entity_ids") or []),
            *(episode.get("primary_place_ids") or []),
            *(episode.get("primary_topic_keys") or []),
        ])
    if any(is_technical_artifact_experience_token(value) for value in values):
        return "Technical artifact is not a user-facing experience."
    return None


def _theme_score(title: str, concrete_anchors: Sequence[str]) -> int:
    if not title or is_generic_experience_anchor(title) or is_technical_artifact_experience_token(title):
        return 0
    if concrete_anchors:
        return 2
    return 1


def _boundary_score(selection: ExperienceSeedSelection, episodes: Sequence[Mapping[str, Any]]) -> int:
    if selection.time_start is None or selection.time_end is None:
        return 0
    if selection.time_end < selection.time_start:
        return 0
    duration = float(selection.time_end) - float(selection.time_start)
    if len(episodes) >= 2 and duration <= 30 * 24 * 60 * 60:
        return 2
    return 1


def _involvement_score(text: str, concrete_anchors: Sequence[str]) -> int:
    if _has_term(text, _ACTION_TERMS):
        return 2
    if any(anchor.casefold().startswith(_RECALL_ANCHOR_PREFIXES) for anchor in concrete_anchors):
        return 1
    return 0


def _process_score(text: str, episodes: Sequence[Mapping[str, Any]]) -> int:
    if len(episodes) >= 3:
        return 2
    if len(episodes) >= 2 or _has_term(text, _PROCESS_TERMS):
        return 1
    return 0


def _recall_score(text: str, concrete_anchors: Sequence[str]) -> int:
    if any(anchor.casefold().startswith(_RECALL_ANCHOR_PREFIXES) for anchor in concrete_anchors):
        return 2
    if _has_term(text, {"trip", "travel", "project", "旅行", "项目"}):
        return 2
    return 1 if concrete_anchors else 0


def _evidence_score(episodes: Sequence[Mapping[str, Any]]) -> int:
    event_count = sum(int(episode.get("source_event_count") or 0) for episode in episodes)
    if len(episodes) >= 2 and event_count >= 8:
        return 2
    if episodes:
        return 1
    return 0


def evaluate_experience_quality(
    *,
    seed: Mapping[str, Any],
    selection: ExperienceSeedSelection,
    evidence_pack: Mapping[str, Any],
) -> ExperienceQualityDecision:
    """Return whether a selected seed is good enough to become an experience."""
    if not selection.is_experience:
        return ExperienceQualityDecision(
            accepted=False,
            score=0,
            reason=selection.reason or "Selection did not form an experience.",
        )

    if str(seed.get("status") or "") == "accepted" or str(seed.get("seed_type") or "") == "manual":
        return ExperienceQualityDecision(
            accepted=True,
            score=MIN_EXPERIENCE_QUALITY_SCORE,
            reason="User accepted this seed.",
            components={"user_confirmed": MIN_EXPERIENCE_QUALITY_SCORE},
        )

    episodes = _included_episodes(selection, evidence_pack)
    artifact = _artifact_reason(seed, selection, episodes)
    if artifact:
        return ExperienceQualityDecision(accepted=False, score=0, reason=artifact)

    concrete_anchors = _concrete(_all_selection_anchors(seed, selection, episodes))
    if not concrete_anchors:
        return ExperienceQualityDecision(
            accepted=False,
            score=0,
            reason="Seed has no concrete anchors.",
        )

    text = _text_blob(seed, selection, episodes)
    components = {
        "theme": _theme_score(selection.title, concrete_anchors),
        "boundary": _boundary_score(selection, episodes),
        "involvement": _involvement_score(text, concrete_anchors),
        "process": _process_score(text, episodes),
        "recall_value": _recall_score(text, concrete_anchors),
        "evidence": _evidence_score(episodes),
    }
    score = sum(components.values())
    mandatory_ok = (
        components["theme"] > 0
        and components["boundary"] > 0
        and components["involvement"] > 0
    )
    if score < MIN_EXPERIENCE_QUALITY_SCORE or not mandatory_ok:
        return ExperienceQualityDecision(
            accepted=False,
            score=score,
            reason="Candidate lacks enough narrative quality to become an experience.",
            components=components,
        )
    return ExperienceQualityDecision(
        accepted=True,
        score=score,
        reason="Candidate passed narrative quality gate.",
        components=components,
    )


__all__ = [
    "ExperienceQualityDecision",
    "MIN_EXPERIENCE_QUALITY_SCORE",
    "evaluate_experience_quality",
]
