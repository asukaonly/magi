from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.events.lifecycle import MessageBusModule
from magi.events.in_memory_backend import InMemoryMessageBusBackend


def _build_message_bus_config() -> SimpleNamespace:
    return SimpleNamespace(
        max_queue_size=128,
        num_workers=1,
        broadcast_max_concurrency=4,
        handler_timeout_seconds=0.5,
    )


@pytest.mark.asyncio
async def test_message_bus_module_initializes_in_memory_backend(tmp_path: Path) -> None:
    import asyncio
    from magi.events.events import Event, EventTypes
    from magi.events.domain_payloads import UserMessageReceived, TaskContext
    from magi.events.payload_helpers import expect_payload

    context = RuntimeBootstrapContext()
    context.core.config = SimpleNamespace(
        agent=SimpleNamespace(
            message_bus=_build_message_bus_config(),
        )
    )
    context.core.runtime_paths = SimpleNamespace(
        message_queue_db_path=tmp_path / "message_queue.db",
    )

    module = MessageBusModule(context)
    await module.init()

    try:
        backend = context.message_bus.message_bus
        assert isinstance(backend, InMemoryMessageBusBackend)

        workers = list(backend._workers)
        assert workers and all(not worker.done() for worker in workers)
        received = []

        async def consume(event):
            received.append(expect_payload(event, UserMessageReceived))

        await backend.subscribe(EventTypes.USER_MESSAGE_RECEIVED, consume)
        payload = UserMessageReceived(content="hello", context=TaskContext("s1", "t1", None, "u1"))
        assert await backend.publish(Event(type=EventTypes.USER_MESSAGE_RECEIVED, data=payload))
        await asyncio.wait_for(backend._queue.join(), timeout=2)
        assert len(received) == 1 and received[0] is payload
        assert received[0].content == "hello" and received[0].metadata == {}
        assert (await backend.get_stats())["processed_count"] == 1
    finally:
        await module.shutdown()

    assert context.message_bus.message_bus is None
    assert all(worker.done() for worker in workers)
