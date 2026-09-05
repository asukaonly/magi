"""Phase 7 of C: SensorStateUpdateSubscriber persists fingerprints."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SensorEventEmitted, TaskContext
from magi.awareness.subscribers.sensor_state_update_subscriber import SensorStateUpdateSubscriber


def _payload(*, fingerprint, sensor_id="x"):
    return SensorEventEmitted(
        sensor_name=sensor_id, payload={}, context=TaskContext(None, None, None, "u"),
        sensor_id=sensor_id, sensor_fingerprint=fingerprint,
        output_dict={"provenance": {"source_connection_id": "test-account"}},
    )


@pytest.fixture
def fake_bus():
    bus = MagicMock()
    bus.subscribe = AsyncMock(return_value="sub-id")
    bus.unsubscribe = AsyncMock(return_value=True)
    return bus


@pytest.fixture
def fake_store():
    s = MagicMock()
    s.start = AsyncMock()
    s.stop = AsyncMock()
    s.drain = AsyncMock()
    s.add_fingerprint = AsyncMock()
    return s


@pytest.mark.asyncio
async def test_persists_fingerprint(fake_bus, fake_store):
    sub = SensorStateUpdateSubscriber(event_bus=fake_bus, sensor_state_writer=fake_store)
    await sub.start()
    payload = _payload(fingerprint="fp-1", sensor_id="screen_time")
    await sub._on_event(Event(type=EventTypes.SENSOR_EVENT_EMITTED, data=payload, event_id="e"))
    await sub.drain()
    fake_store.add_fingerprint.assert_awaited_once_with("test-account:screen_time", "fp-1")


@pytest.mark.asyncio
async def test_skips_when_no_fingerprint(fake_bus, fake_store):
    sub = SensorStateUpdateSubscriber(event_bus=fake_bus, sensor_state_writer=fake_store)
    await sub.start()
    payload = _payload(fingerprint=None)
    await sub._on_event(Event(type=EventTypes.SENSOR_EVENT_EMITTED, data=payload, event_id="e"))
    await sub.drain()
    fake_store.add_fingerprint.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_failure_swallowed(fake_bus, fake_store):
    fake_store.add_fingerprint.side_effect = RuntimeError("disk full")
    sub = SensorStateUpdateSubscriber(event_bus=fake_bus, sensor_state_writer=fake_store)
    await sub.start()
    await sub._on_event(
        Event(type=EventTypes.SENSOR_EVENT_EMITTED, data=_payload(fingerprint="fp"), event_id="e")
    )
    await sub.drain()  # must not raise


@pytest.mark.asyncio
async def test_stop_unsubscribes_and_stops_writer(fake_bus, fake_store):
    sub = SensorStateUpdateSubscriber(event_bus=fake_bus, sensor_state_writer=fake_store)
    await sub.start()
    await sub.stop()

    fake_bus.unsubscribe.assert_awaited_once_with("sub-id")
    fake_store.stop.assert_awaited_once()
