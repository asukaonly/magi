from __future__ import annotations

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event
from magi.memory.l3.models import L3Candidate, ValidationDecision


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
async def test_search_summaries_fuses_bm25_and_vector_hits(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from magi.memory.l3.summary_store import L3SummaryStore

    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l3_store.initialize()

    await l3_store._store_summary(
        {
            "summary_id": "summary-bm25",
            "summary_type": "thematic",
            "summary_category": "topic",
            "period_start": 1.0,
            "period_end": 2.0,
            "content": "remote role planning recap",
            "key_topics": ["job"],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
            "source_event_ids": ["evt-1"],
            "source_event_count": 1,
            "importance_aggregate": 0.7,
            "event_type_distribution": {},
            "generated_by_model": "rule-summary",
            "generation_prompt": None,
            "generation_reason": "thematic:topic:job",
            "created_at": 1.0,
            "updated_at": 1.0,
        }
    )
    await l3_store._store_summary(
        {
            "summary_id": "summary-vector",
            "summary_type": "thematic",
            "summary_category": "topic",
            "period_start": 1.0,
            "period_end": 2.0,
            "content": "growth oriented career summary",
            "key_topics": ["career"],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
            "source_event_ids": ["evt-2"],
            "source_event_count": 1,
            "importance_aggregate": 0.8,
            "event_type_distribution": {},
            "generated_by_model": "rule-summary",
            "generation_prompt": None,
            "generation_reason": "thematic:topic:career",
            "created_at": 1.0,
            "updated_at": 1.0,
        }
    )

    async def _fake_bm25(
        _query: str,
        *,
        summary_type: str | None = None,
        summary_category: str | None = None,
        limit: int = 20,
    ):  # type: ignore[no-untyped-def]
        _ = summary_type, summary_category, limit
        return [("summary-bm25", -1.0)]

    async def _fake_semantic(
        *,
        query: str,
        summary_type: str | None,
        summary_category: str | None,
        limit: int,
    ):  # type: ignore[no-untyped-def]
        _ = query, summary_type, summary_category, limit
        return [{"summary_id": "summary-vector"}]

    monkeypatch.setattr(l3_store, "bm25_search", _fake_bm25)
    monkeypatch.setattr(l3_store, "_semantic_search_summaries", _fake_semantic)

    results = await l3_store.search_summaries(query="career planning", summary_type="thematic", limit=5)

    assert [item["summary_id"] for item in results] == ["summary-bm25", "summary-vector"]


@pytest.mark.asyncio
async def test_search_summaries_filters_summary_category(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from magi.memory.l3.summary_store import L3SummaryStore

    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l3_store.initialize()

    await l3_store._store_summary(
        {
            "summary_id": "summary-state-change",
            "summary_type": "insight",
            "summary_category": "state_change",
            "period_start": 1.0,
            "period_end": 2.0,
            "content": "stress level remained high across the week",
            "key_topics": ["stress"],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
            "source_event_ids": ["evt-1"],
            "source_event_count": 1,
            "importance_aggregate": 0.8,
            "event_type_distribution": {},
            "generated_by_model": "rule-summary",
            "generation_prompt": None,
            "generation_reason": "insight:state_change",
            "created_at": 1.0,
            "updated_at": 1.0,
        }
    )
    await l3_store._store_summary(
        {
            "summary_id": "summary-trend-shift",
            "summary_type": "insight",
            "summary_category": "trend_shift",
            "period_start": 1.0,
            "period_end": 2.0,
            "content": "stress planning shifted toward relief and recovery",
            "key_topics": ["stress"],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
            "source_event_ids": ["evt-2"],
            "source_event_count": 1,
            "importance_aggregate": 0.8,
            "event_type_distribution": {},
            "generated_by_model": "rule-summary",
            "generation_prompt": None,
            "generation_reason": "insight:trend_shift",
            "created_at": 1.0,
            "updated_at": 1.0,
        }
    )

    async def _fake_bm25(_query: str, *, summary_type: str | None = None, summary_category: str | None = None, limit: int = 20):  # type: ignore[no-untyped-def]
        _ = summary_type, summary_category, limit
        return [("summary-state-change", -1.0), ("summary-trend-shift", -0.8)]

    async def _fake_semantic(*, query: str, summary_type: str | None, summary_category: str | None, limit: int):  # type: ignore[no-untyped-def]
        _ = query, summary_type, summary_category, limit
        return [{"summary_id": "summary-trend-shift"}, {"summary_id": "summary-state-change"}]

    monkeypatch.setattr(l3_store, "bm25_search", _fake_bm25)
    monkeypatch.setattr(l3_store, "_semantic_search_summaries", _fake_semantic)

    results = await l3_store.search_summaries(
        query="stress",
        summary_type="insight",
        summary_category="state_change",
        limit=5,
    )

    assert [item["summary_id"] for item in results] == ["summary-state-change"]


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
    ai_event = normalize_runtime_event(
        Event(
            type=EventTypes.AI_RESPONSE,
            data={"user_id": "u1", "session_id": "s1", "message": "You should compare growth and salary tradeoffs."},
            source="chat",
            level=EventLevel.INFO,
            correlation_id="evt-2",
            timestamp=1710000300.0,
        ),
        event_id="evt-2",
    )
    await l1_store.store(chat_event)
    await l1_store.store(ai_event)

    async def _fake_model(_pack):  # type: ignore[no-untyped-def]
        return {
            "content": "LLM rewritten temporal summary",
            "key_topics": ["job_search"],
            "change_and_pattern": {"changes": ["moved from exploration to planning"], "patterns": []},
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
    assert summary["change_and_pattern"] == {"changes": ["moved from exploration to planning"], "patterns": []}
    assert summary["generated_by_model"] == "temporal-llm"
    event_links = await l3_store.list_summary_event_links(summary["summary_id"])
    assert len(event_links) == 2


@pytest.mark.asyncio
async def test_generate_temporal_summary_falls_back_when_llm_disabled(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    l3_store = L3SummaryStore(
        db_path=str(tmp_path / "memory.db"),
        vector_enabled=False,
        enable_temporal_llm_summary=False,
    )
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
    ai_event = normalize_runtime_event(
        Event(
            type=EventTypes.AI_RESPONSE,
            data={"user_id": "u1", "session_id": "s1", "message": "You should compare growth and salary tradeoffs."},
            source="chat",
            level=EventLevel.INFO,
            correlation_id="evt-2",
            timestamp=1710000300.0,
        ),
        event_id="evt-2",
    )
    await l1_store.store(chat_event)
    await l1_store.store(ai_event)

    async def _unexpected_model(_pack):  # type: ignore[no-untyped-def]
        raise AssertionError("LLM path should be disabled")

    monkeypatch.setattr(l3_store._temporal_llm_service, "_call_temporal_model", _unexpected_model)

    summary = await l3_store.generate_temporal_summary(
        l1_store=l1_store,
        summary_category="day",
        period_start=1709990000.0,
        period_end=1710003600.0,
    )

    assert summary is not None
    assert "switch jobs" in summary["content"].lower()
    assert summary["generated_by_model"] == "rule-summary"


@pytest.mark.asyncio
async def test_generate_temporal_summary_falls_back_when_llm_candidate_is_rejected(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3 import summary_store as summary_store_module
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
    ai_event = normalize_runtime_event(
        Event(
            type=EventTypes.AI_RESPONSE,
            data={"user_id": "u1", "session_id": "s1", "message": "You should compare growth and salary tradeoffs."},
            source="chat",
            level=EventLevel.INFO,
            correlation_id="evt-2",
            timestamp=1710000300.0,
        ),
        event_id="evt-2",
    )
    await l1_store.store(chat_event)
    await l1_store.store(ai_event)

    async def _fake_model(_pack):  # type: ignore[no-untyped-def]
        return {
            "content": "LLM rewritten temporal summary",
            "key_topics": ["job_search"],
            "importance_aggregate": 0.9,
        }

    def _fake_validate(candidate, *, evidence_events, task_outcome=None):  # type: ignore[no-untyped-def]
        _ = evidence_events, task_outcome
        if candidate.content == "LLM rewritten temporal summary":
            return ValidationDecision(action="reject", reason="synthetic_rejection")
        return ValidationDecision(action="accept", reason="accepted")

    monkeypatch.setattr(l3_store._temporal_llm_service, "_call_temporal_model", _fake_model)
    monkeypatch.setattr(summary_store_module, "validate_candidate", _fake_validate)

    summary = await l3_store.generate_temporal_summary(
        l1_store=l1_store,
        summary_category="day",
        period_start=1709990000.0,
        period_end=1710003600.0,
    )

    assert summary is not None
    assert "switch jobs" in summary["content"].lower()
    assert summary["generated_by_model"] == "rule-summary"


@pytest.mark.asyncio
async def test_generate_thematic_summary_groups_topic_events_and_links_sources(tmp_path):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l1_store.initialize()
    await l3_store.initialize()

    await l1_store.store(
        normalize_runtime_event(
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
    )
    await l1_store.store(
        normalize_runtime_event(
            Event(
                type=EventTypes.AI_RESPONSE,
                data={"user_id": "u1", "session_id": "s1", "message": "The job market looks stronger for remote roles."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-2",
                timestamp=1710000300.0,
            ),
            event_id="evt-2",
        )
    )
    await l1_store.store(
        normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "message": "I should finish my portfolio first."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-3",
                timestamp=1710000600.0,
            ),
            event_id="evt-3",
        )
    )

    summary = await l3_store.generate_thematic_summary(
        l1_store=l1_store,
        topic="job",
        min_source_count=2,
    )

    assert summary is not None
    assert summary["summary_type"] == "thematic"
    assert summary["summary_category"] == "topic"
    assert summary["key_topics"] == ["job"]
    assert summary["source_event_ids"] == ["evt-2", "evt-1"]
    assert summary["generated_by_model"] == "rule-summary"
    event_links = await l3_store.list_summary_event_links(summary["summary_id"])
    assert {link["event_id"] for link in event_links} == {"evt-1", "evt-2"}


@pytest.mark.asyncio
async def test_generate_thematic_summary_uses_llm_candidate_when_available(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1_store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    l3_store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l1_store.initialize()
    await l3_store.initialize()

    await l1_store.store(
        normalize_runtime_event(
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
    )
    await l1_store.store(
        normalize_runtime_event(
            Event(
                type=EventTypes.AI_RESPONSE,
                data={"user_id": "u1", "session_id": "s1", "message": "The job market looks stronger for remote roles."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-2",
                timestamp=1710000300.0,
            ),
            event_id="evt-2",
        )
    )

    async def _fake_model(_pack):  # type: ignore[no-untyped-def]
        return {
            "content": "Job-switch planning kept centering on remote opportunities.",
            "key_topics": ["job_search", "remote_roles"],
            "importance_aggregate": 0.88,
        }

    monkeypatch.setattr(l3_store._topic_llm_service, "_call_topic_model", _fake_model)

    summary = await l3_store.generate_thematic_summary(
        l1_store=l1_store,
        topic="job",
        min_source_count=2,
    )

    assert summary is not None
    assert summary["summary_type"] == "thematic"
    assert summary["summary_category"] == "topic"
    assert summary["generated_by_model"] == "topic-llm"
    assert summary["content"] == "Job-switch planning kept centering on remote opportunities."
    assert summary["key_topics"] == ["job_search", "remote_roles"]
