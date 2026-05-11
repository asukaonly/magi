"""Deterministic evidence classification for memory governance."""

from __future__ import annotations

from ..event_contracts import MemoryDomain, MemoryEvent
from .models import EvidenceClassification

_EXTERNAL_SOURCES = {"timeline", "sensor", "calendar", "location", "external_feed", "external"}


def classify_event_evidence(event: MemoryEvent) -> EvidenceClassification:
    """Classify a normalized event into an evidence class."""

    speaker_role = _normalized(event.author_type)
    grounding_type = _grounding_type(event, speaker_role)
    semantic_owner = _semantic_owner(speaker_role)
    originality_type = "primary"
    source_event_ids: list[str] = []
    normalized_source = _normalized(event.source)

    if _is_assistant_runtime_derivation(event):
        return EvidenceClassification(
            evidence_class="assistant_runtime_derivation",
            reason_code="runtime_chat_response_action",
            speaker_role=speaker_role,
            grounding_type=grounding_type,
            semantic_owner=semantic_owner,
            originality_type=originality_type,
            source_event_ids=source_event_ids,
        )

    if event.memory_domain == MemoryDomain.RUNTIME_TELEMETRY or speaker_role == "system":
        return EvidenceClassification(
            evidence_class="system_runtime",
            reason_code="runtime_domain",
            speaker_role=speaker_role,
            grounding_type=grounding_type,
            semantic_owner=semantic_owner,
            originality_type=originality_type,
            source_event_ids=source_event_ids,
        )

    if speaker_role in {"external", "sensor"} or normalized_source in _EXTERNAL_SOURCES:
        return EvidenceClassification(
            evidence_class="external_observation",
            reason_code="external_source",
            speaker_role=speaker_role,
            grounding_type=grounding_type,
            semantic_owner=semantic_owner,
            originality_type=originality_type,
            source_event_ids=source_event_ids,
        )

    if speaker_role == "assistant" and grounding_type == "tool_grounded":
        return EvidenceClassification(
            evidence_class="assistant_tool_grounded",
            reason_code="assistant_content_type",
            speaker_role=speaker_role,
            grounding_type=grounding_type,
            semantic_owner=semantic_owner,
            originality_type=originality_type,
            source_event_ids=source_event_ids,
        )

    if speaker_role == "assistant":
        return EvidenceClassification(
            evidence_class="assistant_freeform",
            reason_code="assistant_default",
            speaker_role=speaker_role,
            grounding_type=grounding_type,
            semantic_owner=semantic_owner,
            originality_type=originality_type,
            source_event_ids=source_event_ids,
        )

    if speaker_role == "user":
        return EvidenceClassification(
            evidence_class="user_self_report",
            reason_code="user_default",
            speaker_role=speaker_role,
            grounding_type=grounding_type,
            semantic_owner=semantic_owner,
            originality_type=originality_type,
            source_event_ids=source_event_ids,
        )

    return EvidenceClassification(
        evidence_class="external_observation",
        reason_code="fallback_external",
        speaker_role=speaker_role,
        grounding_type=grounding_type,
        semantic_owner=semantic_owner,
        originality_type=originality_type,
        source_event_ids=source_event_ids,
    )


def _grounding_type(event: MemoryEvent, speaker_role: str | None) -> str | None:
    if speaker_role == "user":
        return "self_reported"
    if speaker_role == "assistant":
        return "tool_grounded" if _normalized(event.content_type) == "tool_result" else "freeform_generated"
    if event.memory_domain == MemoryDomain.RUNTIME_TELEMETRY or speaker_role == "system":
        return "observed"
    if speaker_role in {"external", "sensor", "tool"}:
        return "observed"
    return "observed"


def _semantic_owner(speaker_role: str | None) -> str | None:
    if speaker_role == "user":
        return "user"
    if speaker_role == "assistant":
        return "assistant"
    if speaker_role in {"external", "sensor", "system", "tool"}:
        return "world"
    return None


def _is_assistant_runtime_derivation(event: MemoryEvent) -> bool:
    if str(event.event_type).strip() != "ActionExecuted":
        return False
    if _normalized(event.source) != "runtime_event_emitter":
        return False
    return _normalized(event.source_item_id) == "chatresponseaction"


def _normalized(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


__all__ = ["EvidenceClassification", "classify_event_evidence"]