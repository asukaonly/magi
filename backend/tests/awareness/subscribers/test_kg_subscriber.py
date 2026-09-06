"""Phase 6 of C: KGSubscriber processes relation_candidates → unified_memory.upsert_user_graph_edge."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.awareness.kg_write_queue import KnowledgeGraphEdgeWrite
from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SourceEventEmitted, TaskContext
from magi.timeline.subscribers.kg_subscriber import KGSubscriber


def _make_payload_with_relations(candidates, whitelist):
    return SourceEventEmitted(
        source_name="x", payload={}, context=TaskContext(None, None, None, "u"),
        source_id="x",
        output_dict={"source_type": "external_activity", "source_item_id": "x", "occurred_at": 1.0},
        relation_candidates=tuple(candidates),
        allowed_edge_whitelist=tuple(whitelist),
        occurred_at=1.0,
    )


@pytest.fixture
def fake_bus():
    bus = MagicMock()
    bus.subscribe = AsyncMock(return_value="sub-id")
    bus.unsubscribe = AsyncMock(return_value=True)
    return bus


@pytest.fixture
def fake_writer():
    writer = MagicMock()
    writer.start = AsyncMock()
    writer.stop = AsyncMock()
    writer.drain = AsyncMock()
    writer.add_edge = AsyncMock()
    return writer


@pytest.mark.asyncio
async def test_skips_when_no_relations(fake_bus, fake_writer):
    sub = KGSubscriber(event_bus=fake_bus, kg_writer=fake_writer)
    await sub.start()
    payload = _make_payload_with_relations([], [])
    await sub._on_event(Event(type=EventTypes.SOURCE_EVENT_EMITTED, data=payload, event_id="evt-1"))
    await sub.drain()
    fake_writer.add_edge.assert_not_awaited()


@pytest.mark.asyncio
async def test_processes_whitelisted_relations(fake_bus, fake_writer):
    sub = KGSubscriber(event_bus=fake_bus, kg_writer=fake_writer)
    await sub.start()
    candidates = [
        {"predicate": "VIEWED", "object_id": "tool:chrome", "subject_id": "user:1"},
        {"predicate": "VIEWED", "object_id": "tool:vscode"},
        {"predicate": "INVALID", "object_id": "x"},  # not in whitelist
    ]
    payload = _make_payload_with_relations(candidates, ["VIEWED"])
    await sub._on_event(Event(type=EventTypes.SOURCE_EVENT_EMITTED, data=payload, event_id="evt-X"))
    await sub.drain()
    assert fake_writer.add_edge.await_count == 2
    for call in fake_writer.add_edge.await_args_list:
        edge = call.args[0]
        assert isinstance(edge, KnowledgeGraphEdgeWrite)
        assert edge.evidence_event_ids == ("evt-X",)
        assert edge.predicate == "VIEWED"


@pytest.mark.asyncio
async def test_skips_candidate_without_object_id(fake_bus, fake_writer):
    sub = KGSubscriber(event_bus=fake_bus, kg_writer=fake_writer)
    await sub.start()
    payload = _make_payload_with_relations(
        [{"predicate": "VIEWED", "object_id": ""}],
        ["VIEWED"],
    )
    await sub._on_event(Event(type=EventTypes.SOURCE_EVENT_EMITTED, data=payload, event_id="e"))
    await sub.drain()
    fake_writer.add_edge.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_failure_does_not_break_subscriber(fake_bus, fake_writer):
    fake_writer.add_edge.side_effect = RuntimeError("queue closed")
    sub = KGSubscriber(event_bus=fake_bus, kg_writer=fake_writer)
    await sub.start()
    payload = _make_payload_with_relations(
        [{"predicate": "VIEWED", "object_id": "x"}], ["VIEWED"]
    )
    await sub._on_event(Event(type=EventTypes.SOURCE_EVENT_EMITTED, data=payload, event_id="e"))
    await sub.drain()  # must not raise


@pytest.mark.asyncio
async def test_stop_unsubscribes_and_stops_writer(fake_bus, fake_writer):
    sub = KGSubscriber(event_bus=fake_bus, kg_writer=fake_writer)
    await sub.start()
    await sub.stop()

    fake_bus.unsubscribe.assert_awaited_once_with("sub-id")
    fake_writer.stop.assert_awaited_once()
