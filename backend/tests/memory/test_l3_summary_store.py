from __future__ import annotations

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event


@pytest.mark.asyncio
async def test_l3_summary_excludes_runtime_telemetry_and_keeps_sources(tmp_path):
    from magi.memory.l1_event_store import L1EventStore
    from magi.memory.l3_summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "events.db"))
    l3_store = L3SummaryStore(db_path=str(tmp_path / "summaries.db"))
    await l1_store.initialize()
    await l3_store.initialize()

    chat_event = normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={"user_id": "u1", "session_id": "s1", "message": "I want to switch jobs this year."},
            source="chat",
            level=EventLevel.INFO,
            correlation_id="evt-1",
            timestamp=1710000000.0,
        ),
        event_id="evt-1",
    )
    telemetry_event = normalize_runtime_event(
        Event(
            type=EventTypes.TASK_COMPLETED,
            data={"user_id": "u1", "session_id": "s1", "task_id": "orchestrate"},
            source="runtime",
            level=EventLevel.INFO,
            correlation_id="evt-2",
            timestamp=1710000300.0,
        ),
        event_id="evt-2",
    )

    await l1_store.store(chat_event)
    await l1_store.store(telemetry_event)

    summary = await l3_store.generate_temporal_summary(
        l1_store=l1_store,
        summary_category="day",
        period_start=1709990000.0,
        period_end=1710003600.0,
    )

    assert summary is not None
    assert summary["source_event_count"] == 1
    assert summary["source_event_ids"] == ["evt-1"]
    assert "switch jobs" in summary["content"].lower()
    assert await l1_store.count_events() == 2
