from __future__ import annotations

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event
from magi.memory.l3.models import L3Candidate


@pytest.mark.asyncio
async def test_l3_summary_excludes_runtime_telemetry_and_keeps_sources(tmp_path):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"))
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
    event_links = await l3_store.list_summary_event_links(summary["summary_id"])
    assert len(event_links) == 1
    assert event_links[0]["event_id"] == "evt-1"
    assert await l1_store.count_events() == 1
    assert await l1_store.count_runtime_observations() == 1


@pytest.mark.asyncio
async def test_upsert_candidate_persists_event_and_task_links(tmp_path):
    from magi.memory.l3.summary_store import L3SummaryStore

    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l3_store.initialize()

    summary = await l3_store.upsert_candidate(
        candidate=L3Candidate(
            summary_type="insight",
            summary_category="task_reflection",
            content="The user clarified that growth matters more than salary.",
            source_event_ids=["evt-1", "evt-2"],
        ),
        source_task_ids=["task-1"],
    )

    event_links = await l3_store.list_summary_event_links(summary["summary_id"])
    task_links = await l3_store.list_summary_task_links(summary["summary_id"])

    assert {link["event_id"] for link in event_links} == {"evt-1", "evt-2"}
    assert all(link["link_role"] == "primary" for link in event_links)
    assert len(task_links) == 1
    assert task_links[0]["task_id"] == "task-1"
    assert task_links[0]["link_role"] == "source_task"


@pytest.mark.asyncio
async def test_generate_temporal_summary_uses_llm_candidate_when_available(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
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
    await l1_store.store(chat_event)

    async def _fake_model(_pack):  # type: ignore[no-untyped-def]
        return {
            "content": "LLM rewritten temporal summary",
            "key_topics": ["job_search"],
            "importance_aggregate": 0.9,
        }

    monkeypatch.setattr(l3_store._temporal_llm_service, "_call_temporal_model", _fake_model)

    summary = await l3_store.generate_temporal_summary(
        l1_store=l1_store,
        summary_category="day",
        period_start=1709990000.0,
        period_end=1710003600.0,
    )

    assert summary is not None
    assert summary["content"] == "LLM rewritten temporal summary"
    assert summary["key_topics"] == ["job_search"]
    event_links = await l3_store.list_summary_event_links(summary["summary_id"])
    assert len(event_links) == 1
