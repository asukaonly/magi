from __future__ import annotations

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event


def _build_user_message(*, message: str = "I like sushi.", metadata: dict | None = None):
    return Event(
        type=EventTypes.USER_MESSAGE,
        data={"user_id": "u1", "session_id": "s1", "message": message},
        source="chat",
        level=EventLevel.INFO,
        correlation_id="evt-user-1",
        metadata={"user_id": "u1", **(metadata or {})},
        timestamp=1710000000.0,
    )


def _build_ai_response(*, text: str = "You like sushi.", metadata: dict | None = None):
    return Event(
        type=EventTypes.AI_RESPONSE,
        data={"user_id": "u1", "session_id": "s1", "response": text},
        source="assistant",
        level=EventLevel.INFO,
        correlation_id="evt-ai-1",
        metadata={"user_id": "u1", **(metadata or {})},
        timestamp=1710000001.0,
    )


def _build_timeline_event(*, summary: str = "Calendar shows a meeting tomorrow."):
    return Event(
        type="TIMELINE_EVENT",
        data={"title": "Calendar", "summary": summary},
        source="calendar",
        level=EventLevel.INFO,
        correlation_id="evt-timeline-1",
        metadata={"timeline": {"source_type": "calendar"}, "user_id": "u1"},
        timestamp=1710000002.0,
    )


def _build_runtime_event():
    return Event(
        type=EventTypes.TASK_COMPLETED,
        data={"task_id": "task-1"},
        source="system",
        level=EventLevel.INFO,
        correlation_id="evt-runtime-1",
        metadata={"memory_domain": "runtime_telemetry"},
        timestamp=1710000003.0,
    )


def test_normalized_event_defaults_user_evidence_metadata():
    memory_event = normalize_runtime_event(_build_user_message())

    assert memory_event.speaker_role == "user"
    assert memory_event.grounding_type == "self_reported"
    assert memory_event.derived_from_event_ids == []
    assert memory_event.semantic_owner_hint == "user"
    assert memory_event.originality_type == "primary"


def test_normalized_event_defaults_assistant_evidence_metadata():
    memory_event = normalize_runtime_event(_build_ai_response())

    assert memory_event.speaker_role == "assistant"
    assert memory_event.grounding_type == "freeform_generated"
    assert memory_event.derived_from_event_ids == []
    assert memory_event.originality_type == "primary"


def test_normalized_event_defaults_external_observation_metadata():
    memory_event = normalize_runtime_event(_build_timeline_event())

    assert memory_event.speaker_role == "timeline"
    assert memory_event.grounding_type == "observed"
    assert memory_event.semantic_owner_hint == "world"


def test_normalized_event_defaults_runtime_metadata():
    memory_event = normalize_runtime_event(_build_runtime_event())

    assert memory_event.speaker_role == "system"
    assert memory_event.grounding_type == "observed"
    assert memory_event.semantic_owner_hint == "world"


def test_classifier_maps_user_self_report():
    from magi.memory.l2.evidence_classifier import classify_event_evidence

    classification = classify_event_evidence(normalize_runtime_event(_build_user_message()))

    assert classification.evidence_class == "user_self_report"
    assert classification.reason_code == "user_default"


def test_classifier_maps_user_report_about_others():
    from magi.memory.l2.evidence_classifier import classify_event_evidence

    event = normalize_runtime_event(
        _build_user_message(metadata={"semantic_owner_hint": "third_party"})
    )

    classification = classify_event_evidence(event)

    assert classification.evidence_class == "user_report_about_others"
    assert classification.reason_code == "user_semantic_owner"


def test_classifier_maps_assistant_tool_grounded():
    from magi.memory.l2.evidence_classifier import classify_event_evidence

    event = normalize_runtime_event(
        _build_ai_response(metadata={"tool_name": "weather_api", "tool_call_id": "call-1"})
    )

    classification = classify_event_evidence(event)

    assert classification.evidence_class == "assistant_tool_grounded"
    assert classification.reason_code == "assistant_tool_metadata"


def test_classifier_maps_assistant_quote():
    from magi.memory.l2.evidence_classifier import classify_event_evidence

    event = normalize_runtime_event(
        _build_ai_response(metadata={"derived_from_event_ids": ["evt-user-1"]})
    )

    classification = classify_event_evidence(event)

    assert classification.evidence_class == "assistant_quote"
    assert classification.source_event_ids == ["evt-user-1"]
    assert classification.reason_code == "assistant_derived_history"


def test_classifier_maps_assistant_freeform():
    from magi.memory.l2.evidence_classifier import classify_event_evidence

    classification = classify_event_evidence(normalize_runtime_event(_build_ai_response()))

    assert classification.evidence_class == "assistant_freeform"
    assert classification.reason_code == "assistant_default"


def test_classifier_maps_external_observation():
    from magi.memory.l2.evidence_classifier import classify_event_evidence

    classification = classify_event_evidence(normalize_runtime_event(_build_timeline_event()))

    assert classification.evidence_class == "external_observation"
    assert classification.reason_code == "external_source"


def test_classifier_maps_system_runtime():
    from magi.memory.l2.evidence_classifier import classify_event_evidence

    classification = classify_event_evidence(normalize_runtime_event(_build_runtime_event()))

    assert classification.evidence_class == "system_runtime"
    assert classification.reason_code == "runtime_domain"


def _build_chat_response_action_event():
    return Event(
        type="ActionExecuted",
        data={
            "agent_id": "chat:web_user",
            "event_type": "UserMessage",
            "action_type": "ChatResponseAction",
            "response": "懂你，这种天气确实烦。",
            "user_id": "web_user",
            "session_id": "s1",
            "turn_id": "turn-1",
            "success": True,
        },
        source="runtime_action_emitter",
        level=EventLevel.INFO,
        correlation_id="evt-runtime-chat-1",
        timestamp=1710000004.0,
    )


def test_classifier_maps_assistant_runtime_derivation():
    from magi.memory.l2.evidence_classifier import classify_event_evidence

    classification = classify_event_evidence(normalize_runtime_event(_build_chat_response_action_event()))

    assert classification.evidence_class == "assistant_runtime_derivation"
    assert classification.reason_code == "runtime_chat_response_action"
