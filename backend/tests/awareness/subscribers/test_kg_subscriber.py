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


@pytest.mark.parametrize(
    "relations,predicates", [([], []), ([{"predicate": "VIEWED", "object_id": ""}], ["VIEWED"])]
)
@pytest.mark.asyncio
async def test_subscriber_skips_candidates_without_graph_endpoints(
    fake_bus, fake_writer, relations, predicates
):
    sub = KGSubscriber(event_bus=fake_bus, kg_writer=fake_writer)
    await sub.start()
    payload = _make_payload_with_relations(relations, predicates)
    await sub._on_event(Event(type=EventTypes.SOURCE_EVENT_EMITTED, data=payload, event_id="evt-1"))
    await sub.drain()
    fake_writer.add_edge.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscriber_blocks_direct_bypass_writes(fake_bus, fake_writer):
    sub = KGSubscriber(event_bus=fake_bus, kg_writer=fake_writer)
    await sub.start()
    candidates = [
        {"predicate": "VIEWED", "object_id": "tool:chrome", "subject_id": "user:1"},
        {"predicate": "VIEWED", "object_id": "tool:vscode"},
        {"predicate": "INVALID", "object_id": "x"},
    ]
    payload = _make_payload_with_relations(candidates, ["VIEWED"])
    subscription = fake_bus.subscribe.await_args
    assert subscription.args[0] == EventTypes.SOURCE_EVENT_EMITTED
    await subscription.args[1](
        Event(type=EventTypes.SOURCE_EVENT_EMITTED, data=payload, event_id="evt-X")
    )
    await sub.drain()
    fake_writer.add_edge.assert_not_awaited()
    assert sub.get_stats()["bypass_blocked"] == 3

    await sub.stop()
    fake_bus.unsubscribe.assert_awaited_once_with("sub-id")


@pytest.mark.asyncio
async def test_subscriber_ignores_malformed_events_safely(fake_bus, fake_writer):
    sub = KGSubscriber(event_bus=fake_bus, kg_writer=fake_writer)
    await sub.start()
    handler = fake_bus.subscribe.await_args.args[1]
    try:
        await handler(Event(type=EventTypes.SOURCE_EVENT_EMITTED, data={"bad": True}, event_id="bad-1"))
        await sub.drain()
        fake_writer.add_edge.assert_not_awaited()
    finally:
        await sub.stop()
