"""Deterministic evidence classification for L2 governance."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..event_contracts import MemoryDomain, MemoryEvent

_EXTERNAL_SOURCES = {"timeline", "sensor", "calendar", "location", "external_feed", "external"}


@dataclass(slots=True)
class EvidenceClassification:
    """Classification result used by L2 evidence governance."""

    evidence_class: str
    reason_code: str
    speaker_role: str | None
    grounding_type: str | None
    semantic_owner: str | None
    originality_type: str | None
    source_event_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0


def classify_event_evidence(event: MemoryEvent) -> EvidenceClassification:
    """Classify a normalized event into an evidence class."""

    speaker_role = _normalized(event.speaker_role)
    grounding_type = _normalized(event.grounding_type)
    semantic_owner = _normalized(event.semantic_owner_hint)
    originality_type = _normalized(event.originality_type)
    source_event_ids = [text for item in event.derived_from_event_ids if (text := str(item).strip())]
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

    if speaker_role in {"timeline", "sensor", "external"} or normalized_source in _EXTERNAL_SOURCES:
        return EvidenceClassification(
            evidence_class="external_observation",
            reason_code="external_source",
            speaker_role=speaker_role,
            grounding_type=grounding_type,
            semantic_owner=semantic_owner,
            originality_type=originality_type,
            source_event_ids=source_event_ids,
        )

    if speaker_role == "assistant" and (
        grounding_type == "tool_grounded" or _metadata_has_tool_signals(event)
    ):
        return EvidenceClassification(
            evidence_class="assistant_tool_grounded",
            reason_code="assistant_tool_metadata",
            speaker_role=speaker_role,
            grounding_type=grounding_type,
            semantic_owner=semantic_owner,
            originality_type=originality_type,
            source_event_ids=source_event_ids,
        )

    if speaker_role == "assistant" and (
        source_event_ids or grounding_type == "quoted_from_history"
    ):
        return EvidenceClassification(
            evidence_class="assistant_quote",
            reason_code="assistant_derived_history",
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

    if speaker_role == "user" and semantic_owner in {"third_party", "world"}:
        return EvidenceClassification(
            evidence_class="user_report_about_others",
            reason_code="user_semantic_owner",
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


def _metadata_has_tool_signals(event: MemoryEvent) -> bool:
    metadata = _parse_json_dict(event.metadata)
    return any(metadata.get(key) for key in ("tool_name", "tool_call_id", "tool_result_ref"))


def _is_assistant_runtime_derivation(event: MemoryEvent) -> bool:
    if str(event.event_type).strip() != "ActionExecuted":
        return False
    if _normalized(event.source) != "runtime_action_emitter":
        return False
    payload = _parse_json_dict(event.structured_payload)
    action_type = _normalized(payload.get("action_type"))
    if action_type == "chatresponseaction":
        return True
    response = payload.get("response")
    agent_id = _normalized(payload.get("agent_id"))
    return bool(isinstance(response, str) and response.strip() and agent_id and agent_id.startswith("chat:"))


def _parse_json_dict(raw: str) -> dict[str, object]:
    import json

    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _normalized(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


__all__ = ["EvidenceClassification", "classify_event_evidence"]
