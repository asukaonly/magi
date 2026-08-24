from __future__ import annotations

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import IngestTarget, MemoryDomain, RetentionClass


def test_normalized_memory_event_requires_domain_and_ingest_target():
    from magi.memory.event_contracts import MemoryEvent, normalize_runtime_event

    event = Event(
        type=EventTypes.USER_MESSAGE,
        data={"user_id": "u1", "message": "hello"},
        source="chat",
        level=EventLevel.INFO,
        correlation_id="corr-1",
    )

    normalized = normalize_runtime_event(event)

    assert isinstance(normalized, MemoryEvent)
    assert normalized.memory_domain == MemoryDomain.USER_AUTHORED
    assert normalized.ingest_target == IngestTarget.L1_ONLY
    assert normalized.retention_class == RetentionClass.PERMANENT




def test_task_completed_event_defaults_to_l1_only():
    from magi.memory.event_contracts import normalize_runtime_event

    event = Event(
        type=EventTypes.TASK_COMPLETED,
        data={"task_id": "task-1", "success": True},
        source="runtime",
        level=EventLevel.INFO,
        correlation_id="corr-3",
    )

    normalized = normalize_runtime_event(event)

    assert normalized.ingest_target == IngestTarget.L1_ONLY
    assert normalized.memory_domain == MemoryDomain.RUNTIME_TELEMETRY
    assert normalized.cognition_eligible is False
    assert normalized.retention_class == RetentionClass.COMPRESSIBLE


def test_trace_runtime_event_defaults_to_runtime_only_and_reads_tags():
    from magi.memory.event_contracts import normalize_runtime_event

    event = Event(
        type="TRACE_NODE_COMPLETED",
        data={
            "turn_id": "turn-1",
            "span_id": "turn-1:intent",
            "node_type": "intent_resolution",
            "status": "completed",
            "tags": {
                "user_id": "u1",
                "session_id": "s1",
            },
        },
        source="runtime_event_emitter",
        level=EventLevel.INFO,
        correlation_id="trace-1",
    )

    normalized = normalize_runtime_event(event)

    assert normalized.ingest_target == IngestTarget.RUNTIME_ONLY
    assert normalized.memory_domain == MemoryDomain.RUNTIME_TELEMETRY
    assert normalized.user_id == "u1"
    assert normalized.session_id == "s1"


def test_action_executed_event_defaults_to_runtime_only():
    from magi.memory.event_contracts import normalize_runtime_event

    event = Event(
        type=EventTypes.ACTION_EXECUTED,
        data={
            "user_id": "u1",
            "session_id": "s1",
            "action_type": "ChatResponseAction",
            "success": True,
            "execution_time": 0.25,
        },
        source="runtime_event_emitter",
        level=EventLevel.INFO,
        correlation_id="corr-action-1",
    )

    normalized = normalize_runtime_event(event)

    assert normalized.ingest_target == IngestTarget.RUNTIME_ONLY
    assert normalized.memory_domain == MemoryDomain.RUNTIME_TELEMETRY
    assert normalized.cognition_eligible is False
    assert normalized.retention_class == RetentionClass.DISPOSABLE
