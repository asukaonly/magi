from __future__ import annotations

from magi.events.events import Event, EventLevel, EventTypes


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
    assert normalized.memory_domain == "user_authored"
    assert normalized.ingest_target == "l1_only"
    assert normalized.retention_class == "permanent"


def test_runtime_progress_event_defaults_to_l0_only():
    from magi.memory.event_contracts import normalize_runtime_event

    event = Event(
        type="WORKER_AGENT_PROGRESS",
        data={"worker_id": "worker-1", "message": "halfway"},
        source="worker",
        level=EventLevel.INFO,
        correlation_id="corr-2",
    )

    normalized = normalize_runtime_event(event)

    assert normalized.ingest_target == "l0_only"
    assert normalized.memory_domain == "runtime_telemetry"
    assert normalized.cognition_eligible is False
    assert normalized.retention_class == "disposable"


def test_task_completed_event_defaults_to_l0_and_l1():
    from magi.memory.event_contracts import normalize_runtime_event

    event = Event(
        type=EventTypes.TASK_COMPLETED,
        data={"task_id": "task-1", "success": True},
        source="runtime",
        level=EventLevel.INFO,
        correlation_id="corr-3",
    )

    normalized = normalize_runtime_event(event)

    assert normalized.ingest_target == "l0_and_l1"
    assert normalized.memory_domain == "runtime_telemetry"
    assert normalized.cognition_eligible is False
    assert normalized.retention_class == "compressible"
