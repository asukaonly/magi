"""Serialization helpers for the user-facing episode review surface."""

from __future__ import annotations

import json
from typing import Any, Iterable


def _metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    raw_items: Iterable[Any]
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            decoded = [value]
        raw_items = decoded if isinstance(decoded, list) else [decoded]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = [value]
    return {_clean_text(item) for item in raw_items if _clean_text(item)}


def _fallback_title(episode: dict[str, Any]) -> str:
    episode_id = _clean_text(episode.get("episode_id"))
    return episode_id or "Episode"


def serialize_episodic_summary(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the stable API shape for an L3 episodic summary row."""
    if row is None:
        return None
    metadata = _metadata_dict(row.get("insight_metadata"))
    return {
        "summary_id": row.get("summary_id"),
        "content": _clean_text(row.get("content")),
        "label": _clean_text(metadata.get("label")),
        "updated_at": row.get("updated_at"),
        "is_fallback": bool(metadata.get("fallback")),
    }


def build_episode_display_fields(
    episode: dict[str, Any],
    episode_summary: dict[str, Any] | None,
) -> dict[str, str]:
    """Resolve title and recap fields for the reading-first episode page."""
    summary = episode_summary or {}
    user_title = _clean_text(episode.get("user_label"))
    user_description = _clean_text(episode.get("user_note"))
    generated_title = _first_text(summary.get("label"), episode.get("label"))
    generated_description = _first_text(
        summary.get("content"),
        episode.get("summary"),
        episode.get("slice_narrative"),
    )

    display_title = user_title or generated_title or _fallback_title(episode)
    display_description = user_description or generated_description
    if user_title or user_description:
        display_source = "user_override"
    elif generated_title or generated_description:
        display_source = "generated"
    else:
        display_source = "fallback"

    return {
        "display_title": display_title,
        "display_description": display_description,
        "display_source": display_source,
    }


def serialize_l1_event_preview(
    event: dict[str, Any] | None,
    *,
    membership: dict[str, Any],
) -> dict[str, Any]:
    """Combine an L2 membership row with a compact hydrated L1 event preview."""
    event = event or {}
    content = _first_text(
        event.get("timeline_title"),
        event.get("title"),
        event.get("summary"),
        event.get("content"),
    )
    content_preview = content[:240]
    if len(content) > 240:
        content_preview = f"{content_preview.rstrip()}..."

    event_id = _first_text(event.get("event_id"), membership.get("event_id"))
    return {
        "episode_id": _clean_text(membership.get("episode_id")),
        "event_id": event_id,
        "membership_role": _clean_text(membership.get("membership_role")) or "member",
        "membership_confidence": float(membership.get("membership_confidence") or 0.0),
        "added_at": membership.get("added_at"),
        "timestamp": event.get("timestamp"),
        "event_type": event.get("event_type"),
        "source": event.get("source"),
        "source_item_id": event.get("source_item_id"),
        "content_preview": content_preview,
    }


def score_episode_candidate(
    source: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[float, list[str]]:
    """Score whether two active episodes are useful merge candidates."""
    score = 0.0
    reasons: list[str] = []

    source_start = source.get("time_start")
    source_end = source.get("time_end")
    candidate_start = candidate.get("time_start")
    candidate_end = candidate.get("time_end")
    if all(isinstance(value, (int, float)) for value in (source_start, source_end, candidate_start, candidate_end)):
        if float(candidate_start) <= float(source_end) and float(candidate_end) >= float(source_start):
            score += 4.0
            reasons.append("overlapping_time")
        else:
            gap = min(
                abs(float(candidate_start) - float(source_end)),
                abs(float(source_start) - float(candidate_end)),
            )
            if gap <= 6 * 60 * 60:
                score += 3.0
                reasons.append("nearby_time")
            elif gap <= 24 * 60 * 60:
                score += 1.0
                reasons.append("adjacent_time")

    shared_entities = _string_set(source.get("primary_entity_ids")) & _string_set(candidate.get("primary_entity_ids"))
    shared_places = _string_set(source.get("primary_place_ids")) & _string_set(candidate.get("primary_place_ids"))
    shared_topics = _string_set(source.get("primary_topic_keys")) & _string_set(candidate.get("primary_topic_keys"))
    if shared_entities:
        score += min(3.0, 1.0 + len(shared_entities))
        reasons.append("shared_entities")
    if shared_places:
        score += min(3.0, 1.0 + len(shared_places))
        reasons.append("shared_places")
    if shared_topics:
        score += min(3.0, 1.0 + len(shared_topics))
        reasons.append("shared_topics")
    if _clean_text(source.get("episode_type")) and source.get("episode_type") == candidate.get("episode_type"):
        score += 0.5
        reasons.append("same_type")

    return score, reasons

