from __future__ import annotations

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth, normalize_runtime_event


def _build_user_message(*, message: str = "I like sushi.", metadata: dict | None = None):
    return Event(
        type=EventTypes.USER_MESSAGE,
        data={
            "user_id": "u1",
            "session_id": "s1",
            "content": message,
            "author_type": "user",
            "content_type": "text",
        },
        source="chat",
        level=EventLevel.INFO,
        correlation_id="evt-user-1",
        metadata={"user_id": "u1", **(metadata or {})},
        timestamp=1710000000.0,
    )


def _build_ai_response(*, text: str = "You like sushi.", metadata: dict | None = None):
    return Event(
        type=EventTypes.AI_RESPONSE,
        data={
            "user_id": "u1",
            "session_id": "s1",
            "content": text,
            "author_type": "assistant",
            "content_type": "text",
        },
        source="assistant",
        level=EventLevel.INFO,
        correlation_id="evt-ai-1",
        metadata={"user_id": "u1", **(metadata or {})},
        timestamp=1710000001.0,
    )


def _build_external_observation(*, summary: str = "Calendar shows a meeting tomorrow."):
    return MemoryEvent(
        event_id="evt-timeline-1",
        correlation_id="evt-timeline-1",
        timestamp=1710000002.0,
        created_at=1710000002.0,
        event_type="SENSOR_EVENT",
        source="calendar",
        source_item_id="calendar:item-1",
        memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
        retention_class=RetentionClass.COMPRESSIBLE,
        session_id=None,
        turn_id=None,
        user_id="u1",
        task_id=None,
        content=summary,
        author_type="external",
        content_type="observation",
        importance_score=0.75,
        level=EventLevel.INFO.value,
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

    assert memory_event.author_type == "user"
    assert memory_event.content_type == "text"


def test_normalized_event_defaults_assistant_evidence_metadata():
    memory_event = normalize_runtime_event(_build_ai_response())

    assert memory_event.author_type == "assistant"
    assert memory_event.content_type == "text"


def test_normalized_event_defaults_external_observation_metadata():
    memory_event = _build_external_observation()

    assert memory_event.author_type == "external"
    assert memory_event.content_type == "observation"


def test_normalized_event_defaults_runtime_metadata():
    memory_event = normalize_runtime_event(_build_runtime_event())

    assert memory_event.author_type == "system"
    assert memory_event.content_type == "text"


def test_classifier_maps_user_self_report():
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(normalize_runtime_event(_build_user_message()))

    assert classification.evidence_class == "user_self_report"
    assert classification.reason_code == "user_default"


def test_classifier_maps_assistant_tool_grounded():
    from magi.memory.evidence import classify_event_evidence

    event = normalize_runtime_event(
        Event(
            type=EventTypes.AI_RESPONSE,
            data={
                "user_id": "u1",
                "session_id": "s1",
                "content": "Weather says rain tomorrow.",
                "author_type": "assistant",
                "content_type": "tool_result",
            },
            source="assistant",
            level=EventLevel.INFO,
            correlation_id="evt-ai-tool-1",
            metadata={"user_id": "u1"},
            timestamp=1710000001.0,
        )
    )

    classification = classify_event_evidence(event)

    assert classification.evidence_class == "assistant_tool_grounded"
    assert classification.reason_code == "assistant_content_type"


def test_classifier_maps_assistant_freeform():
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(normalize_runtime_event(_build_ai_response()))

    assert classification.evidence_class == "assistant_freeform"
    assert classification.reason_code == "assistant_default"


def test_classifier_maps_external_observation():
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(_build_external_observation())

    assert classification.evidence_class == "external_observation"
    assert classification.reason_code == "external_source"


def test_classifier_maps_system_runtime():
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(normalize_runtime_event(_build_runtime_event()))

    assert classification.evidence_class == "system_runtime"
    assert classification.reason_code == "runtime_domain"


def _build_chat_response_action_event():
    return Event(
        type="ActionExecuted",
        data={
            "content": "懂你，这种天气确实烦。",
            "author_type": "tool",
            "content_type": "tool_result",
            "action_type": "ChatResponseAction",
            "user_id": "local_user",
            "session_id": "s1",
            "turn_id": "turn-1",
            "success": True,
        },
        source="runtime_event_emitter",
        level=EventLevel.INFO,
        correlation_id="evt-runtime-chat-1",
        timestamp=1710000004.0,
    )


def test_classifier_maps_assistant_runtime_derivation():
    from magi.memory.evidence import classify_event_evidence

    classification = classify_event_evidence(normalize_runtime_event(_build_chat_response_action_event()))

    assert classification.evidence_class == "assistant_runtime_derivation"
    assert classification.reason_code == "runtime_chat_response_action"
