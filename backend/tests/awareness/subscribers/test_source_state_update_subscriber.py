"""Phase 7 of C: SourceStateUpdateSubscriber persists fingerprints."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SourceEventEmitted, TaskContext
from magi.awareness.subscribers.source_state_update_subscriber import SourceStateUpdateSubscriber


def _payload(*, fingerprint, source_id="x"):
    return SourceEventEmitted(
        source_name=source_id, payload={}, context=TaskContext(None, None, None, "u"),
        source_id=source_id, source_fingerprint=fingerprint,
        output_dict={"provenance": {"source_connection_id": "test-account"}},
    )


@pytest.fixture
def fake_store():
    s = MagicMock()
    s.start = AsyncMock()
    s.stop = AsyncMock()
    s.drain = AsyncMock()
    s.add_fingerprint = AsyncMock()
    return s


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_first", [False, True])
async def test_registered_fingerprint_subscriber_recovers_and_stops(fake_store, fail_first, caplog):
    import asyncio
    from magi.events.in_memory_backend import InMemoryMessageBusBackend
    from unittest.mock import call

    bus = InMemoryMessageBusBackend()
    await bus.start()
    if fail_first:
        fake_store.add_fingerprint.side_effect = [RuntimeError("disk full"), None]
    sub = SourceStateUpdateSubscriber(event_bus=bus, source_state_writer=fake_store)
    try:
        await sub.start()
        fake_store.start.assert_awaited_once()
        for fingerprint in [None, "first", "second"]:
            await bus.publish(
                Event(
                    type=EventTypes.SOURCE_EVENT_EMITTED,
                    data=_payload(fingerprint=fingerprint, source_id="screen_time"),
                )
            )
            await asyncio.wait_for(bus._queue.join(), timeout=1)
            await sub.drain()
        assert fake_store.add_fingerprint.await_args_list == [
            call("test-account:screen_time", "first"),
            call("test-account:screen_time", "second"),
        ]
        if fail_first:
            assert "disk full" in caplog.text
        await sub.stop()
        fake_store.stop.assert_awaited_once()
        await bus.publish(
            Event(type=EventTypes.SOURCE_EVENT_EMITTED, data=_payload(fingerprint="after-stop"))
        )
        await asyncio.wait_for(bus._queue.join(), timeout=1)
        assert fake_store.add_fingerprint.await_count == 2
    finally:
        await sub.stop()
        await bus.stop()
