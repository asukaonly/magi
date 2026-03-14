from __future__ import annotations

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event


def _tool_event(*, event_id: str, success: bool, timestamp: float, error: str | None = None):
    return normalize_runtime_event(
        Event(
            type=EventTypes.ACTION_EXECUTED,
            data={
                "action_type": "browser.open",
                "params": {"url": "https://example.com"},
                "success": success,
                "execution_time": 0.5,
                "error": error,
                "session_id": "s1",
                "user_id": "u1",
            },
            source="worker",
            level=EventLevel.INFO if success else EventLevel.ERROR,
            correlation_id=event_id,
            timestamp=timestamp,
        ),
        event_id=event_id,
    )


@pytest.mark.asyncio
async def test_l4_tracks_success_rate_and_queryable_strategy(tmp_path):
    from magi.memory.l4_procedural_memory import L4ProceduralMemoryStore

    store = L4ProceduralMemoryStore(db_path=str(tmp_path / "l4.db"))
    await store.initialize()

    await store.record_memory_event(_tool_event(event_id="evt-1", success=True, timestamp=1710000000.0))
    await store.record_memory_event(_tool_event(event_id="evt-2", success=True, timestamp=1710000100.0))
    await store.record_memory_event(_tool_event(event_id="evt-3", success=False, timestamp=1710000200.0, error="timeout"))

    skill = await store.get_skill(skill_name="browser.open", skill_category="tool")
    strategies = await store.query_strategies(query="browser", limit=5)

    assert skill is not None
    assert skill["total_attempts"] == 3
    assert skill["success_rate"] == pytest.approx(2 / 3, rel=1e-3)
    assert strategies[0]["skill_name"] == "browser.open"


@pytest.mark.asyncio
async def test_l4_opens_and_recovers_circuit_breaker(tmp_path):
    from magi.memory.l4_procedural_memory import L4ProceduralMemoryStore

    store = L4ProceduralMemoryStore(db_path=str(tmp_path / "l4.db"), breaker_failure_threshold=3)
    await store.initialize()

    await store.record_memory_event(_tool_event(event_id="evt-1", success=False, timestamp=1710000000.0, error="e1"))
    await store.record_memory_event(_tool_event(event_id="evt-2", success=False, timestamp=1710000100.0, error="e2"))
    await store.record_memory_event(_tool_event(event_id="evt-3", success=False, timestamp=1710000200.0, error="e3"))

    opened = await store.get_skill(skill_name="browser.open", skill_category="tool")
    assert opened is not None
    assert opened["circuit_breaker_state"] == "open"

    await store.record_memory_event(_tool_event(event_id="evt-4", success=True, timestamp=1710000300.0))
    half_open = await store.get_skill(skill_name="browser.open", skill_category="tool")
    assert half_open is not None
    assert half_open["circuit_breaker_state"] == "half_open"

    await store.record_memory_event(_tool_event(event_id="evt-5", success=True, timestamp=1710000400.0))
    recovered = await store.get_skill(skill_name="browser.open", skill_category="tool")
    assert recovered is not None
    assert recovered["circuit_breaker_state"] == "closed"
