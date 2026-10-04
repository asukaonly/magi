"""Indexical routing must preserve historical evidence and caller time bounds."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from magi.events.events import Event, EventTypes
from magi.memory.event_contracts import normalize_runtime_event
from magi.memory.hybrid_retrieval.models import ConversationTurn, RetrievalConfig, RetrievalQuery
from magi.memory.hybrid_retrieval.service import HybridRetrievalService
from magi.memory.l1.event_store import L1EventStore
from magi.memory.l2.store import L2CognitionStore


@pytest_asyncio.fixture
async def historical_memory(tmp_path):
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    l2 = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await l2.initialize()
    for event_id, content, source, event_type, timestamp in [
        ("old-name", "Please call me codename.", "chat", EventTypes.USER_MESSAGE, 1600000000.0),
        (
            "new-weather",
            "Today the weather is sunny.",
            "chat",
            EventTypes.USER_MESSAGE,
            1700000100.0,
        ),
        (
            "external-name",
            "Please call me codename.",
            "chrome_history",
            "SourceActivity",
            1600000000.0,
        ),
    ]:
        await l1.store(
            normalize_runtime_event(
                Event(
                    type=event_type,
                    event_id=event_id,
                    source=source,
                    timestamp=timestamp,
                    data={
                        "content": content,
                        "author_type": "user" if source == "chat" else "external",
                        "content_type": "text",
                        "user_id": "u1",
                        "session_id": "history",
                    },
                )
            )
        )
    assert {row[0] for row in await l1.bm25_search("codename", limit=10)} == {
        "old-name", "external-name"
    }
    try:
        yield SimpleNamespace(l0=None, l1=l1, l2=l2, l2_entity_catalog=None, l3=None, l4=None)
    finally:
        await l1.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "time_range,expected_ids",
    [
        ({}, ["old-name"]),
        ({"start": 1599999999.0, "end": 1600000001.0}, ["old-name"]),
        ({"start": 1700000000.0, "end": 1700000200.0}, []),
    ],
)
async def test_indexical_recall_finds_old_conversation_without_inventing_time_bounds(
    historical_memory, time_range, expected_ids
):
    request = RetrievalQuery(
        query="当时 codename",
        query_mode="exact_fact",
        user_id="u1",
        time_range=time_range,
        conversation_context=[
            ConversationTurn(role="user", content="你知道我是谁吗", timestamp=1700000070.0),
            ConversationTurn(role="assistant", content="codename", timestamp=1700000100.0),
        ],
    )
    service = HybridRetrievalService(
        historical_memory, config=RetrievalConfig(intent_decider_llm_enabled=False)
    )
    decision = AsyncMock(wraps=service._intent_decider.decide)
    service._intent_decider.decide = decision
    payload = await service.query(request)
    assert [event["event_id"] for event in payload.l1_events] == expected_ids
    assert payload.trace["indexical_resolved"] is True
    assert payload.trace["indexical_cue"] == "当时"
    assert payload.trace["mode_source"] == "indexical_override"
    assert payload.trace["resolved_query_mode"] == "episode_recall"
    assert payload.trace["l1_retrieval_scopes"] == ["conversation_only"]
    decision.assert_awaited_once()
    assert decision.await_args.args[0].raw_time_range == (time_range or None)
    assert request.time_range == time_range
    assert request.query_mode == "exact_fact"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,mode,expected_mode,source,orphaned",
    [
        ("当时 codename", "event_stream", "event_stream", "caller", "当时"),
        ("codename", "event_stream", "event_stream", "caller", None),
        ("codename", None, "exact_fact", "default", None),
    ],
)
async def test_unresolved_indexical_input_preserves_executed_mode(
    historical_memory, monkeypatch, query, mode, expected_mode, source, orphaned
):
    from magi.memory.hybrid_retrieval import service_plan_execution

    execute = AsyncMock(wraps=service_plan_execution.execute_layer_plan)
    monkeypatch.setattr(service_plan_execution, "execute_layer_plan", execute)
    service = HybridRetrievalService(
        historical_memory, config=RetrievalConfig(intent_decider_llm_enabled=False)
    )
    payload = await service.query(RetrievalQuery(query=query, query_mode=mode, user_id="u1"))
    assert {event["event_id"] for event in payload.l1_events} == (
        {"old-name", "external-name"} if expected_mode == "event_stream" else {"external-name"}
    )
    assert payload.trace["mode_source"] == source
    assert payload.trace["resolved_query_mode"] == expected_mode
    assert payload.trace.get("indexical_cue_orphaned") == orphaned
    assert "indexical_resolved" not in payload.trace
    assert "inferred_mode" not in payload.trace
    layers = [call.args[0].layer for call in execute.await_args_list]
    assert layers == (["L1"] if expected_mode == "event_stream" else ["L2", "L1"])
