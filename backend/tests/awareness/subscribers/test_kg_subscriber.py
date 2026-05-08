"""Phase 6 of C: KGSubscriber processes relation_candidates → unified_memory.upsert_user_graph_edge."""
from __future__ import annotations
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SensorEventEmitted, TaskContext
from magi.awareness.subscribers.kg_subscriber import KGSubscriber


def _make_payload_with_relations(candidates, whitelist):
    return SensorEventEmitted(
        sensor_name="x", payload={}, context=TaskContext(None, None, None, "u"),
        sensor_id="x",
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
def fake_memory():
    m = MagicMock()
    m.upsert_user_graph_edge = AsyncMock(return_value=None)
    return m


@pytest.mark.asyncio
async def test_skips_when_no_relations(fake_bus, fake_memory):
    sub = KGSubscriber(event_bus=fake_bus, unified_memory=fake_memory)
    await sub.start()
    payload = _make_payload_with_relations([], [])
    await sub._on_event(Event(type=EventTypes.SENSOR_EVENT_EMITTED, data=payload, event_id="evt-1"))
    await sub.drain()
    fake_memory.upsert_user_graph_edge.assert_not_awaited()


@pytest.mark.asyncio
async def test_processes_whitelisted_relations(fake_bus, fake_memory):
    sub = KGSubscriber(event_bus=fake_bus, unified_memory=fake_memory)
    await sub.start()
    candidates = [
        {"predicate": "VIEWED", "object_id": "tool:chrome", "subject_id": "user:1"},
        {"predicate": "VIEWED", "object_id": "tool:vscode"},
        {"predicate": "INVALID", "object_id": "x"},  # not in whitelist
    ]
    payload = _make_payload_with_relations(candidates, ["VIEWED"])
    await sub._on_event(Event(type=EventTypes.SENSOR_EVENT_EMITTED, data=payload, event_id="evt-X"))
    await sub.drain()
    # Two `uses` candidates persisted; INVALID skipped
    assert fake_memory.upsert_user_graph_edge.await_count == 2
    # evidence_event_ids carries envelope id
    for call in fake_memory.upsert_user_graph_edge.await_args_list:
        assert call.kwargs["evidence_event_ids"] == ["evt-X"]


@pytest.mark.asyncio
async def test_skips_candidate_without_object_id(fake_bus, fake_memory):
    sub = KGSubscriber(event_bus=fake_bus, unified_memory=fake_memory)
    await sub.start()
    payload = _make_payload_with_relations(
        [{"predicate": "VIEWED", "object_id": ""}],
        ["VIEWED"],
    )
    await sub._on_event(Event(type=EventTypes.SENSOR_EVENT_EMITTED, data=payload, event_id="e"))
    await sub.drain()
    fake_memory.upsert_user_graph_edge.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_failure_does_not_break_subscriber(fake_bus, fake_memory):
    fake_memory.upsert_user_graph_edge.side_effect = RuntimeError("DB down")
    sub = KGSubscriber(event_bus=fake_bus, unified_memory=fake_memory)
    await sub.start()
    payload = _make_payload_with_relations(
        [{"predicate": "VIEWED", "object_id": "x"}], ["VIEWED"]
    )
    await sub._on_event(Event(type=EventTypes.SENSOR_EVENT_EMITTED, data=payload, event_id="e"))
    await sub.drain()  # must not raise


@pytest.mark.asyncio
async def test_supports_sync_upsert(fake_bus):
    """If unified_memory.upsert_user_graph_edge returns non-awaitable (sync fn)."""
    memory = MagicMock()
    memory.upsert_user_graph_edge = MagicMock(return_value=None)  # NOT AsyncMock
    sub = KGSubscriber(event_bus=fake_bus, unified_memory=memory)
    await sub.start()
    payload = _make_payload_with_relations(
        [{"predicate": "VIEWED", "object_id": "x"}], ["VIEWED"]
    )
    await sub._on_event(Event(type=EventTypes.SENSOR_EVENT_EMITTED, data=payload, event_id="e"))
    await sub.drain()
    memory.upsert_user_graph_edge.assert_called_once()


@pytest.mark.asyncio
async def test_limits_concurrent_relation_processing(fake_bus, fake_memory):
    active = 0
    max_seen = 0

    async def upsert_user_graph_edge(**kwargs):
        nonlocal active, max_seen
        _ = kwargs
        active += 1
        max_seen = max(max_seen, active)
        await asyncio.sleep(0.01)
        active -= 1

    fake_memory.upsert_user_graph_edge.side_effect = upsert_user_graph_edge
    sub = KGSubscriber(event_bus=fake_bus, unified_memory=fake_memory, max_concurrency=2)
    await sub.start()

    for index in range(10):
        payload = _make_payload_with_relations(
            [{"predicate": "VIEWED", "object_id": f"site:{index}"}],
            ["VIEWED"],
        )
        await sub._on_event(
            Event(
                type=EventTypes.SENSOR_EVENT_EMITTED,
                data=payload,
                event_id=f"evt-{index}",
            )
        )
    await sub.drain()

    assert max_seen <= 2
