from __future__ import annotations

import asyncio

import pytest

from magi.awareness.sensor_hub import SensorHub
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.events.contracts import RefreshLLMConfigCommand, SensorStateFlushCommand, SensorSyncCommand, UserMessageCommand
from magi.events.events import EventTypes
from magi.events.lifecycle import RuntimeCommandProcessorModule
from magi.events.in_memory_backend import InMemoryMessageBusBackend
from magi.events.runtime_queue import SQLiteRuntimeCommandQueue


async def _start_in_memory_message_bus() -> InMemoryMessageBusBackend:
    message_bus = InMemoryMessageBusBackend(
        num_workers=1,
        max_queue_size=64,
    )
    await message_bus.start()
    return message_bus


@pytest.mark.asyncio
async def test_runtime_command_processor_publishes_user_message_to_local_bus(tmp_path: Path) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_in_memory_message_bus()

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
                workspace_path="/tmp/magi",
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
        assert event.payload["workspace_path"] == "/tmp/magi"

        for _ in range(100):
            stats = await queue.get_stats()
            if stats["completed_count"] == 1:
                break
            await asyncio.sleep(0.02)

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
    message_bus = await _start_in_memory_message_bus()

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
    message_bus = await _start_in_memory_message_bus()

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
    message_bus = await _start_in_memory_message_bus()

    class _FakeSensorSchedulerContrib:
        def __init__(self) -> None:
            self.queued_sources: list[dict[str, object]] = []

        async def queue_manual_sync(
            self,
            source_name: str,
            *,
            first_context: bool = False,
            sync_mode: str = "latest",
            backfill_scope: str | None = None,
            backfill_days: int | None = None,
            backfill_start_date: str | None = None,
            backfill_end_date: str | None = None,
        ):
            self.queued_sources.append(
                {
                    "source_name": source_name,
                    "first_context": first_context,
                    "sync_mode": sync_mode,
                    "backfill_scope": backfill_scope,
                    "backfill_days": backfill_days,
                    "backfill_start_date": backfill_start_date,
                    "backfill_end_date": backfill_end_date,
                }
            )
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
                first_context=True,
            )
        )

        for _ in range(100):
            stats = await queue.get_stats()
            if stats["completed_count"] == 1:
                break
            await asyncio.sleep(0.02)

        stats = await queue.get_stats()
        assert stats["completed_count"] == 1
        assert sensor_scheduler.queued_sources == [
            {
                "source_name": "calendar",
                "first_context": True,
                "sync_mode": "latest",
                "backfill_scope": None,
                "backfill_days": None,
                "backfill_start_date": None,
                "backfill_end_date": None,
            }
        ]
    finally:
        await processor.shutdown()
        await message_bus.stop()
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_processor_queues_backfill_sensor_sync(tmp_path: Path) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_in_memory_message_bus()

    class _FakeSensorSchedulerContrib:
        def __init__(self) -> None:
            self.queued_sources: list[dict[str, object]] = []

        async def queue_manual_sync(
            self,
            source_name: str,
            *,
            first_context: bool = False,
            sync_mode: str = "latest",
            backfill_scope: str | None = None,
            backfill_days: int | None = None,
            backfill_start_date: str | None = None,
            backfill_end_date: str | None = None,
        ):
            self.queued_sources.append(
                {
                    "source_name": source_name,
                    "first_context": first_context,
                    "sync_mode": sync_mode,
                    "backfill_scope": backfill_scope,
                    "backfill_days": backfill_days,
                    "backfill_start_date": backfill_start_date,
                    "backfill_end_date": backfill_end_date,
                }
            )
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
                source_name="chrome_history",
                sync_mode="backfill",
                backfill_scope="custom",
                backfill_start_date="2026-06-01",
                backfill_end_date="2026-06-30",
            )
        )

        for _ in range(100):
            stats = await queue.get_stats()
            if stats["completed_count"] == 1:
                break
            await asyncio.sleep(0.02)

        stats = await queue.get_stats()
        assert stats["completed_count"] == 1
        assert sensor_scheduler.queued_sources == [
            {
                "source_name": "chrome_history",
                "first_context": False,
                "sync_mode": "backfill",
                "backfill_scope": "custom",
                "backfill_days": None,
                "backfill_start_date": "2026-06-01",
                "backfill_end_date": "2026-06-30",
            }
        ]
    finally:
        await processor.shutdown()
        await message_bus.stop()
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_processor_flushes_sensor_state(tmp_path: Path) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_in_memory_message_bus()

    class _FakeSensorSyncExecutor:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def flush_sensor_state(self, source_name: str):
            self.calls.append(source_name)
            return {"bucket_count": 1}

    executor = _FakeSensorSyncExecutor()

    context = RuntimeBootstrapContext()
    context.runtime_commands.runtime_command_queue = queue
    context.message_bus.message_bus = message_bus
    context.agent_runtime.agent_runtime = object()
    context.agent_runtime.sensor_sync_executor = executor

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
        assert executor.calls == ["screen_time"]
    finally:
        await processor.shutdown()
        await message_bus.stop()
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_processor_requeues_user_messages_without_local_subscriber(
    tmp_path,
) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_in_memory_message_bus()

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
            stats = await queue.get_stats()
            if stats["completed_count"] == 0 and (stats["pending_count"] > 0 or stats["claimed_count"] > 0):
                break
            await asyncio.sleep(0.02)

        stats = await queue.get_stats()
        assert stats["completed_count"] == 0
        assert stats["pending_count"] > 0 or stats["claimed_count"] > 0

        sensor_hub = SensorHub(message_bus=message_bus)
        await sensor_hub.start()
        try:
            # Generous wall-clock budgets (~6s each): this poll-based test runs
            # late in the full suite where leaked aiosqlite worker threads jitter
            # the event loop, so tight 2-3s budgets flake under load.
            for _ in range(300):
                stats = await queue.get_stats()
                if stats["completed_count"] == 1:
                    break
                await asyncio.sleep(0.02)

            for _ in range(300):
                batch = await sensor_hub.get_batch(max_items=8, timeout_seconds=0.02)
                if batch:
                    break
            else:
                batch = []
        finally:
            await sensor_hub.stop()

        assert len(batch) == 1
        assert batch[0].event_type == EventTypes.USER_MESSAGE

        stats = await queue.get_stats()
        assert stats["completed_count"] == 1
    finally:
        await processor.shutdown()
        await message_bus.stop()
        await queue.stop()
