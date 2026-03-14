from __future__ import annotations

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event


async def _build_user_message(text: str, *, correlation_id: str, timestamp: float):
    return normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={"user_id": "u1", "session_id": "s1", "message": text},
            source="chat",
            level=EventLevel.INFO,
            correlation_id=correlation_id,
            metadata={"user_id": "u1"},
            timestamp=timestamp,
        ),
        event_id=correlation_id,
    )


async def _build_group_timeline_message(text: str, *, correlation_id: str, timestamp: float):
    return normalize_runtime_event(
        Event(
            type="TIMELINE_EVENT",
            data={"title": "Group chat", "summary": text},
            source="group_chat",
            level=EventLevel.INFO,
            correlation_id=correlation_id,
            metadata={"timeline": {"source_type": "group_chat"}, "user_id": "u1"},
            timestamp=timestamp,
        ),
        event_id=correlation_id,
    )


async def _build_contradiction(text: str, *, correlation_id: str, timestamp: float):
    return normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={"user_id": "u1", "session_id": "s1", "message": text},
            source="chat",
            level=EventLevel.INFO,
            correlation_id=correlation_id,
            metadata={"user_id": "u1"},
            timestamp=timestamp,
        ),
        event_id=correlation_id,
    )


import pytest


@pytest.mark.asyncio
async def test_tom_assertion_starts_tentative_with_low_confidence(tmp_path):
    from magi.memory.l2_cognition_store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    event = await _build_user_message(
        "I have been really stressed about work lately.",
        correlation_id="evt-1",
        timestamp=1710000000.0,
    )
    result = await store.apply_memory_event(event)

    assertions = await store.list_tom_assertions(entity_id="user:u1")

    assert result["assertion_count"] == 1
    assert assertions[0]["trait_name"] == "stress_level"
    assert assertions[0]["validation_state"] == "tentative"
    assert assertions[0]["confidence_score"] <= 0.3


@pytest.mark.asyncio
async def test_repeated_evidence_promotes_snapshot_to_stable(tmp_path):
    from magi.memory.l2_cognition_store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    events = [
        await _build_user_message(
            "I feel stressed about work.",
            correlation_id="evt-1",
            timestamp=1710000000.0,
        ),
        await _build_user_message(
            "Work pressure is making me anxious again.",
            correlation_id="evt-2",
            timestamp=1710090000.0,
        ),
        await _build_user_message(
            "The job competition still feels stressful.",
            correlation_id="evt-3",
            timestamp=1710185000.0,
        ),
    ]

    for event in events:
        await store.apply_memory_event(event)

    assertions = await store.list_tom_assertions(entity_id="user:u1")
    snapshot = await store.get_tom_snapshot(entity_id="user:u1", entity_type="user")

    assert assertions[0]["validation_state"] == "stable"
    assert assertions[0]["confidence_score"] >= 0.8
    assert snapshot is not None
    assert snapshot["core_traits"]["stress_level"] == "high"


@pytest.mark.asyncio
async def test_contradiction_downgrades_existing_assertion(tmp_path):
    from magi.memory.l2_cognition_store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    for correlation_id, timestamp, text in (
        ("evt-1", 1710000000.0, "I feel stressed about work."),
        ("evt-2", 1710090000.0, "The workload still makes me anxious."),
        ("evt-3", 1710185000.0, "Work pressure is stressing me out."),
    ):
        await store.apply_memory_event(
            await _build_user_message(text, correlation_id=correlation_id, timestamp=timestamp)
        )

    await store.apply_memory_event(
        await _build_contradiction(
            "I actually feel calm and relaxed about work now.",
            correlation_id="evt-4",
            timestamp=1710275000.0,
        )
    )

    assertions = await store.list_tom_assertions(entity_id="user:u1")

    assert assertions[0]["validation_state"] == "contradicted"
    assert assertions[0]["confidence_score"] < 0.8


@pytest.mark.asyncio
async def test_group_content_avoids_deep_psychology(tmp_path):
    from magi.memory.l2_cognition_store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.apply_memory_event(
        await _build_group_timeline_message(
            "The group felt tense and Alice openly praised Bob.",
            correlation_id="evt-1",
            timestamp=1710000000.0,
        )
    )

    assertions = await store.list_tom_assertions(entity_id="user:u1")

    assert assertions == []
