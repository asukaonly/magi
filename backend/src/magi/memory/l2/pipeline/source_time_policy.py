"""Host-owned source policy for Claim evidence time semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ...event_contracts import MemoryEvent

TIMESTAMP_QUALITIES = frozenset(
    {
        "exact",
        "calendar_anchor",
        "approximate_recorded",
        "derived_order",
        "low",
    }
)
TRUSTED_CURRENTNESS_QUALITIES = frozenset({"exact", "calendar_anchor"})

_HISTORY_CONFIDENCE_POLICY = {
    "exact": ("exact", "message_timestamp"),
    "explicit": ("exact", "message_timestamp"),
    "message_timestamp": ("exact", "message_timestamp"),
    "frontmatter": ("calendar_anchor", "frontmatter"),
    "source_name": ("calendar_anchor", "source_name"),
    "document_heading": ("calendar_anchor", "document_heading"),
    "calendar_anchor": ("calendar_anchor", "content_calendar_anchor"),
    "file_mtime": ("approximate_recorded", "file_mtime"),
    "sync_time": ("approximate_recorded", "sync_time"),
    "captured_at": ("approximate_recorded", "captured_at"),
    "imported_at": ("approximate_recorded", "imported_at"),
    "file_order": ("derived_order", "file_order"),
    "source_order": ("derived_order", "source_order"),
    "derived_order": ("derived_order", "derived_order"),
}
_LIVE_CHAT_EVENT_TYPES = frozenset({"usermessage", "user_message", "airesponse", "ai_response"})
_EXACT_MANUAL_SOURCES = frozenset({"manual_entry"})


@dataclass(frozen=True, slots=True)
class SourceTimeSemantics:
    """Normalized source timestamp semantics accepted by the host."""

    timestamp_confidence: str
    timestamp_quality: str
    timestamp_anchor_source: str | None


def resolve_event_time_semantics(event: MemoryEvent) -> SourceTimeSemantics:
    """Classify one event without trusting arbitrary plugin quality strings."""

    return resolve_source_time_semantics(
        source=event.source,
        event_type=event.event_type,
        metadata=event.metadata_json or {},
    )


def resolve_source_time_semantics(
    *,
    source: str,
    event_type: str,
    metadata: Mapping[str, Any] | None,
) -> SourceTimeSemantics:
    """Resolve source time semantics from the closed host policy registry."""

    payload = metadata if isinstance(metadata, Mapping) else {}
    history = payload.get("history_import")
    if isinstance(history, Mapping):
        confidence = _normalized_text(history.get("timestamp_confidence")) or "unknown"
        quality, default_anchor = _HISTORY_CONFIDENCE_POLICY.get(
            confidence,
            ("low", None),
        )
        declared_anchor = _normalized_text(history.get("timestamp_anchor_source"))
        anchor = declared_anchor if declared_anchor == default_anchor else default_anchor
        return SourceTimeSemantics(confidence, quality, anchor)

    normalized_source = _normalized_text(source)
    normalized_event_type = _normalized_text(event_type)
    if normalized_event_type in _LIVE_CHAT_EVENT_TYPES:
        return SourceTimeSemantics("exact", "exact", "message_timestamp")
    if normalized_source in _EXACT_MANUAL_SOURCES:
        return SourceTimeSemantics("exact", "exact", "manual_entry_event_at")
    if "calendar" in normalized_source and normalized_event_type == "source_event":
        return SourceTimeSemantics(
            "calendar_anchor",
            "calendar_anchor",
            "source_occurred_at",
        )
    return SourceTimeSemantics("unknown", "low", None)


def _normalized_text(value: object) -> str:
    return str(value or "").strip().casefold()


__all__ = [
    "SourceTimeSemantics",
    "TIMESTAMP_QUALITIES",
    "TRUSTED_CURRENTNESS_QUALITIES",
    "resolve_event_time_semantics",
    "resolve_source_time_semantics",
]
