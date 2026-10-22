"""Serialization helpers for the user-facing L2 episode review surface."""

from __future__ import annotations

import json
import re
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


def _summary_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text.startswith("{"):
            return {}
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return _partial_summary_payload(text)
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _partial_summary_payload(text: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    for key in ("label", "title", "content", "summary", "description", "recap", "text"):
        value = _extract_json_string_field(text, key)
        if value:
            payload[key] = value
    return payload


def _extract_json_string_field(text: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*("(?:\\.|[^"\\])*")', text)
    if not match:
        return ""
    try:
        decoded = json.loads(match.group(1))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    return decoded if isinstance(decoded, str) else ""


def _summary_content_text(value: Any) -> str:
    payload = _summary_payload(value)
    if payload:
        return _first_text(
            payload.get("content"),
            payload.get("summary"),
            payload.get("description"),
            payload.get("recap"),
            payload.get("text"),
        )
    return _clean_text(value)


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
    content_payload = _summary_payload(row.get("content"))
    return {
        "summary_id": row.get("summary_id"),
        "content": _summary_content_text(row.get("content")),
        "label": _first_text(content_payload.get("label"), content_payload.get("title"), metadata.get("label")),
        "updated_at": row.get("updated_at"),
        "is_fallback": bool(metadata.get("fallback")),
    }


def build_episode_display_fields(
    episode: dict[str, Any],
    episode_summary: dict[str, Any] | None,
) -> dict[str, str]:
    """Resolve title and recap fields for the reading-first episode page."""
    summary = episode_summary or {}
    episode_summary_payload = _summary_payload(episode.get("summary"))
    slice_narrative_payload = _summary_payload(episode.get("slice_narrative"))
    user_title = _clean_text(episode.get("user_label"))
    user_description = _clean_text(episode.get("user_note"))
    generated_title = _first_text(
        summary.get("label"),
        episode_summary_payload.get("label"),
        episode_summary_payload.get("title"),
        slice_narrative_payload.get("label"),
        slice_narrative_payload.get("title"),
        episode.get("label"),
    )
    generated_description = _first_text(
        summary.get("content"),
        _summary_content_text(episode.get("summary")),
        _summary_content_text(episode.get("slice_narrative")),
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


def score_event_candidate(
    episode: dict[str, Any],
    event: dict[str, Any],
) -> tuple[float, list[str]]:
    """Score whether an L1 event is a useful add-candidate for an episode."""
    score = 0.0
    reasons: list[str] = []
    timestamp = event.get("timestamp")
    start = episode.get("time_start")
    end = episode.get("time_end")
    if isinstance(timestamp, (int, float)) and isinstance(start, (int, float)) and isinstance(end, (int, float)):
        if float(start) <= float(timestamp) <= float(end):
            score += 4.0
            reasons.append("within_time_range")
        else:
            gap = min(abs(float(timestamp) - float(start)), abs(float(timestamp) - float(end)))
            if gap <= 6 * 60 * 60:
                score += 2.0
                reasons.append("nearby_time")
            elif gap <= 24 * 60 * 60:
                score += 0.5
                reasons.append("adjacent_time")

    metadata = event.get("metadata_json") if isinstance(event.get("metadata_json"), dict) else {}
    event_topics = _string_set(metadata.get("topics") or metadata.get("topic_keys"))
    event_places = _string_set(metadata.get("place_ids") or metadata.get("places"))
    if event_topics & _string_set(episode.get("primary_topic_keys")):
        score += 2.0
        reasons.append("shared_topics")
    if event_places & _string_set(episode.get("primary_place_ids")):
        score += 2.0
        reasons.append("shared_places")
    if _clean_text(event.get("source")):
        score += 0.25
        reasons.append("same_source_context")
    return score, reasons
