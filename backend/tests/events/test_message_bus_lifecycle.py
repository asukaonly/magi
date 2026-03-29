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

        stats = await backend.get_stats()
        assert stats["queue_length"] == 0
        assert stats["subscriber_count"] == 0
    finally:
        await module.shutdown()
