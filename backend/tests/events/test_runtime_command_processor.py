from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from magi.awareness.sensor_hub import SensorHub
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.events.contracts import UserMessageCommand
from magi.events.events import EventTypes
from magi.events.lifecycle import RuntimeCommandProcessorModule
from magi.events.memory_backend import MemoryMessageBackend
from magi.events.runtime_queue import SQLiteRuntimeCommandQueue


@pytest.mark.asyncio
async def test_runtime_command_processor_publishes_user_message_to_local_bus(tmp_path: Path) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = MemoryMessageBackend()
    await message_bus.start()

    sensor_hub = SensorHub(message_bus=message_bus)
    await sensor_hub.start()

    context = RuntimeBootstrapContext()
    context.runtime_commands.runtime_command_queue = queue
    context.message_bus.message_bus = message_bus
    context.agent_runtime.agent_runtime = object()

    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.01)
    await processor.init()

    try:
        await queue.enqueue_user_message(
            UserMessageCommand(
                source="api",
                user_id="user-1",
                session_id="session-1",
                turn_id="turn-1",
                message="hello runtime",
                runtime_namespace="desktop",
                metadata={"origin": "test"},
                attachments=[{"kind": "pdf", "attachment_id": "att-1"}],
                workspace_path="/Users/asuka/code/magi",
            )
        )

        for _ in range(100):
            batch = await sensor_hub.get_batch(max_items=8, timeout_seconds=0.02)
            if batch:
                break
        else:
            batch = []

        assert len(batch) == 1
        event = batch[0]
        assert event.event_type == EventTypes.USER_MESSAGE
        assert event.payload["content"] == "hello runtime"
        assert event.payload["user_id"] == "user-1"
        assert event.payload["attachments"] == [{"kind": "pdf", "attachment_id": "att-1"}]
        assert event.payload["workspace_path"] == "/Users/asuka/code/magi"

        stats = await queue.get_stats()
        assert stats["completed_count"] == 1
    finally:
        await processor.shutdown()
        await sensor_hub.stop()
        await message_bus.stop()
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_processor_stops_claiming_commands_while_draining(tmp_path: Path) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = MemoryMessageBackend()
    await message_bus.start()

    sensor_hub = SensorHub(message_bus=message_bus)
    await sensor_hub.start()

    context = RuntimeBootstrapContext()
    context.runtime_commands.runtime_command_queue = queue
    context.message_bus.message_bus = message_bus
    context.agent_runtime.agent_runtime = object()

    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.01)
    await processor.init()

    try:
        processor.begin_draining()
        await queue.enqueue_user_message(
            UserMessageCommand(
                source="api",
                user_id="user-1",
                session_id="session-1",
                turn_id="turn-1",
                message="hello drain",
                runtime_namespace="desktop",
                metadata={"origin": "test"},
            )
        )

        await asyncio.sleep(0.05)

        batch = await sensor_hub.get_batch(max_items=8, timeout_seconds=0.02)
        assert batch == []

        stats = await queue.get_stats()
        assert stats["pending_count"] == 1
        assert processor.is_draining is True
    finally:
        await processor.shutdown()
        await sensor_hub.stop()
        await message_bus.stop()
        await queue.stop()
