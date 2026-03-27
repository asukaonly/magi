from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.events.lifecycle import MessageBusModule
from magi.events.sqlite_backend import SQLiteMessageBackend


def _build_message_bus_config() -> SimpleNamespace:
    return SimpleNamespace(
        max_queue_size=128,
        num_workers=1,
        db_path="~/.magi/data/message_queue.db",
        broadcast_max_concurrency=4,
        handler_timeout_seconds=0.5,
        max_retries=3,
        retry_delay_seconds=0.05,
    )


@pytest.mark.asyncio
async def test_message_bus_module_initializes_sqlite_backend(tmp_path: Path) -> None:
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
        assert isinstance(backend, SQLiteMessageBackend)

        health = await backend.get_queue_health()
        assert health["pending"] == 0
        assert health["processing"] == 0
        assert health["failed"] == 0
    finally:
        await module.shutdown()
