"""Shared helpers for deterministic L3 insight rendering."""

from __future__ import annotations

import json
from typing import Any

from ...i18n import is_effective_zh_language


_TRAIT_LABELS_ZH = {
    "music_interests": "音乐兴趣",
    "music.genres": "音乐类型偏好",
    "music.artists": "音乐艺人偏好",
    "preference.music.genres": "音乐类型偏好",
    "preference.music.artists": "常听艺人",
    "stress_level": "压力水平",
    "mood": "情绪状态",
    "engagement": "投入度",
}

_TRAIT_LABELS_EN = {
    "music_interests": "music interests",
    "music.genres": "music genres",
    "music.artists": "music artists",
    "preference.music.genres": "music genres",
    "preference.music.artists": "frequent artists",
    "stress_level": "stress level",
    "mood": "mood",
    "engagement": "engagement",
}

_TRAIT_GROUP_LABELS_ZH = {
    "music_preferences": "音乐偏好",
}

_TRAIT_GROUP_LABELS_EN = {
    "music_preferences": "music preferences",
}

def wants_zh() -> bool:
    """Return whether generated user-facing insight text should use zh-CN."""
    return is_effective_zh_language(default="en")


def trait_label(trait_name: str, *, zh: bool) -> str | None:
    """Translate a trait_name to a human label, or None on dictionary miss.

    This is a strict translator. When the dictionary doesn't cover the
    trait_name, we return None rather than mangling the raw identifier
    (e.g. ``state.sleep_quality`` → ``"state sleep quality"``). Callers
    must handle None by using a higher-level label (trait_family) or
    by abandoning the rendering.
    """
    normalized = str(trait_name or "").strip()
    if not normalized:
        return None
    if zh:
        return _TRAIT_LABELS_ZH.get(normalized)
    return _TRAIT_LABELS_EN.get(normalized)


def trait_group(trait_name: str) -> str:
    normalized = str(trait_name or "").strip()
    if (
        normalized in {"music_interests", "music.artists", "music.genres"}
        or normalized.startswith("preference.music.")
    ):
        return "music_preferences"
    return normalized


def trait_group_label(group_name: str, *, zh: bool) -> str | None:
    """Translate a trait_group to a human label, or None on miss."""
    normalized = str(group_name or "").strip()
    if not normalized:
        return None
    if zh:
        direct = _TRAIT_GROUP_LABELS_ZH.get(normalized)
        if direct:
            return direct
        # Fall back to direct trait_label lookup (might also return None).
        return trait_label(normalized, zh=zh)
    direct = _TRAIT_GROUP_LABELS_EN.get(normalized)
    if direct:
        return direct
    return trait_label(normalized, zh=zh)


_TRAIT_FAMILY_LABELS_ZH: dict[str, str] = {
    "state_profile":         "状态",
    "mood":                  "情绪",
    "stress":                "压力",
    "engagement":            "投入度",
    "trigger":               "触发因素",
    "communication_profile": "沟通偏好",
    "preference_profile":    "偏好",
    "routine_profile":       "行为节律",
    "identity_profile":      "身份信息",
    "relationship_shift":    "关系变化",
    "group_atmosphere":      "群体氛围",
    "public_sentiment":      "公众情绪",
}

_TRAIT_FAMILY_LABELS_EN: dict[str, str] = {
    "state_profile":         "state",
    "mood":                  "mood",
    "stress":                "stress",
    "engagement":            "engagement",
    "trigger":               "trigger",
    "communication_profile": "communication preference",
    "preference_profile":    "preference",
    "routine_profile":       "routine",
    "identity_profile":      "identity",
    "relationship_shift":    "relationship",
    "group_atmosphere":      "group atmosphere",
    "public_sentiment":      "public sentiment",
}


def trait_family_label(family: str, *, zh: bool) -> str | None:
    """Translate a closed-enum trait_family to a human label, or None on miss."""
    normalized = str(family or "").strip()
    if not normalized:
        return None
    if zh:
        return _TRAIT_FAMILY_LABELS_ZH.get(normalized)
    return _TRAIT_FAMILY_LABELS_EN.get(normalized)


def state_change_phrase(statuses: list[str], *, zh: bool) -> str:
    normalized = {str(status or "").strip().lower() for status in statuses}
    if zh:
        if "contradicted" in normalized:
            return "出现不一致信息"
        if "superseded" in normalized:
            return "有了新的判断"
        if "user_rejected" in normalized:
            return "已按用户反馈排除"
        if normalized == {"stable"}:
            return "比较稳定"
        if normalized <= {"corroborated", "stable"}:
            return "更明确"
        return "有更新"
    if "contradicted" in normalized:
        return "has conflicting evidence"
    if "superseded" in normalized:
        return "has a newer reading"
    if "user_rejected" in normalized:
        return "was rejected by the user"
    if normalized == {"stable"}:
        return "looks stable"
    if normalized <= {"corroborated", "stable"}:
        return "is clearer"
    return "has an update"


def decode_value(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def canonicalize_value(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    if isinstance(value, list):
        return sorted(
            (canonicalize_value(item) for item in value),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
    if isinstance(value, dict):
        return {str(key): canonicalize_value(item) for key, item in sorted(value.items())}
    return value


def normalized_value_for_key(value: str) -> str:
    decoded = decode_value(value)
    return json.dumps(
        canonicalize_value(decoded),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _value_terms(value: object) -> list[str]:
    if isinstance(value, list):
        terms: list[str] = []
        for item in value:
            terms.extend(_value_terms(item))
        return terms
    if isinstance(value, dict):
        return [f"{key}: {format_value(item)}" for key, item in value.items()]
    formatted = str(value).replace("_", " ").strip()
    return [formatted] if formatted else []


def format_value(value: object) -> str:
    return "、".join(_dedupe_terms(_value_terms(value)))


def _dedupe_terms(terms: list[str]) -> list[str]:
    visible: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = " ".join(str(term).casefold().split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        visible.append(str(term).strip())
    return visible


def compact_values(values: list[object], *, zh: bool, limit: int = 6) -> str:
    terms: list[str] = []
    for value in values:
        terms.extend(_value_terms(value))
    deduped_terms = _dedupe_terms(terms)
    visible = deduped_terms[:limit]
    if len(deduped_terms) > limit:
        visible.append(f"等 {len(deduped_terms)} 项" if zh else f"and {len(deduped_terms)} total items")
    return ("、" if zh else ", ").join(visible)


def source_event_ids_from_outcomes(outcomes: list[Any]) -> list[str]:
    event_ids: list[str] = []
    for outcome in outcomes:
        for event_id in getattr(outcome, "evidence_event_ids", []) or []:
            normalized = str(event_id).strip()
            if normalized and normalized not in event_ids:
                event_ids.append(normalized)
    return event_ids
