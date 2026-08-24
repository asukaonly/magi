from __future__ import annotations
import pytest
from dependency_injector import providers
from unittest.mock import AsyncMock, MagicMock

from magi.core.container import Container, init_container
from magi.events.events import EventTypes
from magi.events.domain_payloads import SpanCompleted
from magi.runtime_trace.span_publisher import publish_trace_span, resolve_event_bus


def test_resolve_event_bus_uses_global_container_instance():
    container = init_container()
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=True)
    container.message_bus.override(providers.Object(bus))

    try:
        assert Container.message_bus() is not bus
        assert resolve_event_bus() is bus
    finally:
        container.message_bus.reset_override()


@pytest.mark.asyncio
async def test_publishes_span_completed_with_required_fields():
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=True)
    await publish_trace_span(
        event_bus=bus,
        node_type="span",
        name="x",
        trace_id="t1",
        started_at_ms=100,
        ended_at_ms=200,
        attributes={"k": "v"},
    )
    bus.publish.assert_awaited_once()
    event = bus.publish.await_args.args[0]
    assert event.type == EventTypes.SPAN_COMPLETED
    payload: SpanCompleted = event.data
    assert payload.node_type == "span"
    assert payload.duration_ms == 100
    assert payload.attributes == {"k": "v"}


@pytest.mark.asyncio
async def test_publish_failure_is_swallowed():
    bus = MagicMock()
    bus.publish = AsyncMock(side_effect=RuntimeError("dead"))
    # Must not raise
    await publish_trace_span(
        event_bus=bus, node_type="span", name="x", trace_id="t",
        started_at_ms=0, ended_at_ms=0,
    )
