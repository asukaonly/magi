from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiosqlite
import pytest

from magi.awareness.sensor_hub import SensorHub
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.events.contracts import RefreshLLMConfigCommand, SensorStateFlushCommand, SensorSyncCommand, UserMessageCommand
from magi.events.events import EventTypes
from magi.events.lifecycle import RuntimeCommandProcessorModule
from magi.events.runtime_queue import SQLiteRuntimeCommandQueue
from magi.events.sqlite_backend import SQLiteMessageBackend, STATUS_COMPLETED, STATUS_PENDING


async def _read_message_bus_status(db_path: Path) -> str | None:
    async with aiosqlite.connect(str(db_path)) as db:
        cursor = await db.execute(
            "SELECT status FROM message_queue ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    return str(row[0])


async def _read_message_bus_metadata(db_path: Path) -> dict[str, object] | None:
    async with aiosqlite.connect(str(db_path)) as db:
        cursor = await db.execute(
            "SELECT metadata FROM message_queue ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
    if row is None or row[0] is None:
        return None
    return json.loads(str(row[0]))


async def _start_sqlite_message_bus(db_path: Path) -> SQLiteMessageBackend:
    message_bus = SQLiteMessageBackend(
        db_path=str(db_path),
        num_workers=1,
        retry_delay_seconds=0.05,
    )
    await message_bus.start()
    return message_bus


@pytest.mark.asyncio
async def test_runtime_command_processor_publishes_user_message_to_local_bus(tmp_path: Path) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_sqlite_message_bus(tmp_path / "message_queue.db")

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
async def test_runtime_command_processor_refreshes_llm_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_sqlite_message_bus(tmp_path / "message_queue.db")

    context = RuntimeBootstrapContext()
    context.runtime_commands.runtime_command_queue = queue
    context.message_bus.message_bus = message_bus
    context.agent_runtime.agent_runtime = object()

    calls: list[str] = []

    def _fake_reload_config():  # type: ignore[no-untyped-def]
        calls.append("reload")
        return object()

    def _fake_refresh_runtime_llm_config(config):  # type: ignore[no-untyped-def]
        assert config is not None
        calls.append("refresh")

    monkeypatch.setattr("magi.config.loader.reload_config", _fake_reload_config)
    monkeypatch.setattr("magi.bootstrap.backend.refresh_runtime_llm_config", _fake_refresh_runtime_llm_config)

    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.01)
    await processor.init()

    try:
        await queue.enqueue_refresh_llm_config(
            RefreshLLMConfigCommand(
                source="api",
                reason="settings_saved",
            )
        )

        for _ in range(100):
            stats = await queue.get_stats()
            if stats["completed_count"] == 1:
                break
            await asyncio.sleep(0.02)

        stats = await queue.get_stats()
        assert stats["completed_count"] == 1
        assert calls == ["reload", "refresh"]
    finally:
        await processor.shutdown()
        await message_bus.stop()


@pytest.mark.asyncio
async def test_runtime_command_processor_stops_claiming_commands_while_draining(tmp_path: Path) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_sqlite_message_bus(tmp_path / "message_queue.db")

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


@pytest.mark.asyncio
async def test_runtime_command_processor_queues_sensor_sync(tmp_path: Path) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_sqlite_message_bus(tmp_path / "message_queue.db")

    class _FakeSensorSchedulerContrib:
        def __init__(self) -> None:
            self.queued_sources: list[str] = []

        async def queue_manual_sync(self, source_name: str):
            self.queued_sources.append(source_name)
            return type("Schedule", (), {"schedule_id": f"manual:{source_name}"})()

    sensor_scheduler = _FakeSensorSchedulerContrib()

    context = RuntimeBootstrapContext()
    context.runtime_commands.runtime_command_queue = queue
    context.message_bus.message_bus = message_bus
    context.agent_runtime.agent_runtime = object()
    context.agent_runtime.sensor_scheduler_contrib = sensor_scheduler

    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.01)
    await processor.init()

    try:
        await queue.enqueue_sensor_sync(
            SensorSyncCommand(
                source="api",
                source_name="calendar",
            )
        )

        for _ in range(100):
            stats = await queue.get_stats()
            if stats["completed_count"] == 1:
                break
            await asyncio.sleep(0.02)

        stats = await queue.get_stats()
        assert stats["completed_count"] == 1
        assert sensor_scheduler.queued_sources == ["calendar"]
    finally:
        await processor.shutdown()
        await message_bus.stop()
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_processor_flushes_sensor_state(tmp_path: Path) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_sqlite_message_bus(tmp_path / "message_queue.db")

    class _FakeSensor:
        supports_state_flush = True

        def __init__(self) -> None:
            self.calls: list[tuple[object, dict[str, object]]] = []

        async def flush_runtime_state(self, *, runtime_paths, plugin_settings):
            self.calls.append((runtime_paths, plugin_settings))
            return {"bucket_count": 1}

    sensor = _FakeSensor()

    context = RuntimeBootstrapContext()
    context.runtime_commands.runtime_command_queue = queue
    context.message_bus.message_bus = message_bus
    context.agent_runtime.agent_runtime = object()
    context.core.runtime_paths = type(
        "Paths",
        (),
        {"plugin_cache_dir": lambda self, plugin_id: tmp_path / "cache" / plugin_id},
    )()
    context.plugins.sensor_registry = type(
        "Registry",
        (),
        {"resolve_source_sensor": lambda self, source_name: ("screen-time", "timeline.screen_time", sensor, object()) if source_name == "screen_time" else None},
    )()
    context.plugins.plugin_manager = type(
        "Manager",
        (),
        {"get_package": lambda self, plugin_id: type("Package", (), {"current_settings": {"sensors": {"screen_time": {"enabled": True}}}})() if plugin_id == "screen-time" else None},
    )()

    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.01)
    await processor.init()

    try:
        await queue.enqueue_sensor_state_flush(
            SensorStateFlushCommand(
                source="api",
                source_name="screen_time",
            )
        )

        for _ in range(100):
            stats = await queue.get_stats()
            if stats["completed_count"] == 1:
                break
            await asyncio.sleep(0.02)

        stats = await queue.get_stats()
        assert stats["completed_count"] == 1
        assert len(sensor.calls) == 1
        assert sensor.calls[0][1] == {"sensors": {"screen_time": {"enabled": True}}}
    finally:
        await processor.shutdown()
        await message_bus.stop()
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_processor_marks_user_messages_for_subscriber_delivery_on_sqlite_bus(
    tmp_path: Path,
) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus_db = tmp_path / "message_queue.db"
    message_bus = await _start_sqlite_message_bus(message_bus_db)

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
                message="hello sqlite runtime",
                runtime_namespace="desktop",
                metadata={"origin": "test"},
            )
        )

        for _ in range(100):
            if await _read_message_bus_metadata(message_bus_db) is not None:
                break
            await asyncio.sleep(0.02)

        metadata = await _read_message_bus_metadata(message_bus_db)
        assert metadata is not None
        assert metadata["require_subscriber_delivery"] is True

        sensor_hub = SensorHub(message_bus=message_bus)
        await sensor_hub.start()
        try:
            for _ in range(150):
                batch = await sensor_hub.get_batch(max_items=8, timeout_seconds=0.02)
                if batch:
                    break
            else:
                batch = []
        finally:
            await sensor_hub.stop()

        assert len(batch) == 1
        assert batch[0].event_type == EventTypes.USER_MESSAGE

        for _ in range(100):
            if await _read_message_bus_status(message_bus_db) == STATUS_COMPLETED:
                break
            await asyncio.sleep(0.02)

        assert await _read_message_bus_status(message_bus_db) == STATUS_COMPLETED

        stats = await queue.get_stats()
        assert stats["completed_count"] == 1
    finally:
        await processor.shutdown()
        await message_bus.stop()
        await queue.stop()
