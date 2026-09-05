from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from magi.awareness.source_hub import SourceHub
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.events.contracts import (
    RefreshLLMConfigCommand,
    RuntimeCommandType,
    RuntimeQueuedCommand,
    SourceStateFlushCommand,
    SourceSyncCommand,
    UserMessageCommand,
)
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
async def test_runtime_command_processor_publishes_user_message_to_local_bus(
    tmp_path: Path,
) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_in_memory_message_bus()

    source_hub = SourceHub(message_bus=message_bus)
    await source_hub.start()

    context = RuntimeBootstrapContext()
    context.runtime_commands.runtime_command_queue = queue
    context.message_bus.message_bus = message_bus
    context.agent_runtime.agent_runtime = object()

    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.01)
    await processor.init()

    try:
        runtime_command_id = await queue.enqueue_user_message(
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
            batch = await source_hub.get_batch(max_items=8, timeout_seconds=0.02)
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
        assert event.delivery_attempt_no == 0
        assert event.runtime_command_id == runtime_command_id

        for _ in range(100):
            stats = await queue.get_stats()
            if stats["claimed_count"] == 1:
                break
            await asyncio.sleep(0.02)

        stats = await queue.get_stats()
        assert stats["claimed_count"] == 1
        assert stats["completed_count"] == 0
    finally:
        await processor.shutdown()
        await source_hub.stop()
        await message_bus.stop()
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_user_message_event_identity_includes_delivery_attempt() -> None:
    class _RecordingBus:
        def __init__(self) -> None:
            self.events = []

        async def publish(self, event):
            self.events.append(event)
            return True

    command = RuntimeQueuedCommand(
        command_id=73,
        command_type=RuntimeCommandType.USER_MESSAGE,
        payload=UserMessageCommand(
            source="api",
            user_id="user-1",
            session_id="session-1",
            turn_id="turn-1",
            message="hello",
            correlation_id="user_message:message-1",
        ).to_payload(),
        correlation_id="user_message:message-1",
        delivery_attempt_no=4,
    )
    bus = _RecordingBus()
    processor = RuntimeCommandProcessorModule(RuntimeBootstrapContext())

    assert await processor._publish_user_message_command(command, bus)
    assert len(bus.events) == 1
    event = bus.events[0]
    assert event.correlation_id == "user_message:message-1"
    assert event.data["delivery_attempt_no"] == 4
    assert event.data["runtime_command_id"] == 73
    digest = uuid.uuid5(
        uuid.NAMESPACE_URL,
        "magi:runtime-user-message:user_message:message-1:4:73",
    ).hex
    assert event.event_id == f"runtime-user-message:4:73:{digest}"


@pytest.mark.asyncio
async def test_runtime_command_processor_refreshes_llm_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    monkeypatch.setattr(
        "magi.bootstrap.backend.refresh_runtime_llm_config", _fake_refresh_runtime_llm_config
    )

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
async def test_runtime_command_processor_stops_claiming_commands_while_draining(
    tmp_path: Path,
) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_in_memory_message_bus()

    source_hub = SourceHub(message_bus=message_bus)
    await source_hub.start()

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

        batch = await source_hub.get_batch(max_items=8, timeout_seconds=0.02)
        assert batch == []

        stats = await queue.get_stats()
        assert stats["pending_count"] == 1
        assert processor.is_draining is True
    finally:
        await processor.shutdown()
        await source_hub.stop()
        await message_bus.stop()
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_processor_queues_source_sync(tmp_path: Path) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_in_memory_message_bus()

    class _FakeSourceSchedulerContrib:
        def __init__(self) -> None:
            self.queued_sources: list[dict[str, object]] = []

        async def queue_manual_sync(
            self,
            source_name: str,
            *,
            connection_id: str,
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
                    "connection_id": connection_id,
                    "first_context": first_context,
                    "sync_mode": sync_mode,
                    "backfill_scope": backfill_scope,
                    "backfill_days": backfill_days,
                    "backfill_start_date": backfill_start_date,
                    "backfill_end_date": backfill_end_date,
                }
            )
            return type("Schedule", (), {"schedule_id": f"manual:{source_name}"})()

    source_scheduler = _FakeSourceSchedulerContrib()

    context = RuntimeBootstrapContext()
    context.runtime_commands.runtime_command_queue = queue
    context.message_bus.message_bus = message_bus
    context.agent_runtime.agent_runtime = object()
    context.agent_runtime.source_scheduler_contrib = source_scheduler

    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.01)
    await processor.init()

    try:
        await queue.enqueue_source_sync(
            SourceSyncCommand(
                source="api",
                connection_id="account-main",
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
        assert source_scheduler.queued_sources == [
            {
                "source_name": "calendar",
                "connection_id": "account-main",
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
async def test_runtime_command_processor_queues_backfill_source_sync(tmp_path: Path) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_in_memory_message_bus()

    class _FakeSourceSchedulerContrib:
        def __init__(self) -> None:
            self.queued_sources: list[dict[str, object]] = []

        async def queue_manual_sync(
            self,
            source_name: str,
            *,
            connection_id: str,
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
                    "connection_id": connection_id,
                    "first_context": first_context,
                    "sync_mode": sync_mode,
                    "backfill_scope": backfill_scope,
                    "backfill_days": backfill_days,
                    "backfill_start_date": backfill_start_date,
                    "backfill_end_date": backfill_end_date,
                }
            )
            return type("Schedule", (), {"schedule_id": f"manual:{source_name}"})()

    source_scheduler = _FakeSourceSchedulerContrib()

    context = RuntimeBootstrapContext()
    context.runtime_commands.runtime_command_queue = queue
    context.message_bus.message_bus = message_bus
    context.agent_runtime.agent_runtime = object()
    context.agent_runtime.source_scheduler_contrib = source_scheduler

    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.01)
    await processor.init()

    try:
        await queue.enqueue_source_sync(
            SourceSyncCommand(
                source="api",
                connection_id="account-main",
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
        assert source_scheduler.queued_sources == [
            {
                "source_name": "chrome_history",
                "connection_id": "account-main",
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
async def test_runtime_command_processor_flushes_source_state(tmp_path: Path) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_in_memory_message_bus()

    class _FakeSourceSyncExecutor:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def flush_source_state(self, source_name: str, *, connection_id: str):
            assert connection_id == "account-main"
            self.calls.append(source_name)
            return {"bucket_count": 1}

    executor = _FakeSourceSyncExecutor()

    context = RuntimeBootstrapContext()
    context.runtime_commands.runtime_command_queue = queue
    context.message_bus.message_bus = message_bus
    context.agent_runtime.agent_runtime = object()
    context.agent_runtime.source_sync_executor = executor

    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.01)
    await processor.init()

    try:
        await queue.enqueue_source_state_flush(
            SourceStateFlushCommand(
                source="api",
                connection_id="account-main",
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
            if stats["completed_count"] == 0 and (
                stats["pending_count"] > 0 or stats["claimed_count"] > 0
            ):
                break
            await asyncio.sleep(0.02)

        stats = await queue.get_stats()
        assert stats["completed_count"] == 0
        assert stats["pending_count"] > 0 or stats["claimed_count"] > 0

        source_hub = SourceHub(message_bus=message_bus)
        await source_hub.start()
        try:
            # Generous wall-clock budgets (~6s each): this poll-based test runs
            # late in the full suite where leaked aiosqlite worker threads jitter
            # the event loop, so tight 2-3s budgets flake under load.
            for _ in range(300):
                batch = await source_hub.get_batch(max_items=8, timeout_seconds=0.02)
                if batch:
                    break
            else:
                batch = []
        finally:
            await source_hub.stop()

        assert len(batch) == 1
        assert batch[0].event_type == EventTypes.USER_MESSAGE

        stats = await queue.get_stats()
        assert stats["claimed_count"] == 1
        assert stats["completed_count"] == 0
    finally:
        await processor.shutdown()
        await message_bus.stop()
        await queue.stop()


@pytest.mark.asyncio
async def test_global_clear_waits_for_claimed_user_message_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_in_memory_message_bus()
    source_hub = SourceHub(message_bus=message_bus)
    await source_hub.start()

    context = RuntimeBootstrapContext()
    context.runtime_commands.runtime_command_queue = queue
    context.message_bus.message_bus = message_bus
    context.agent_runtime.agent_runtime = object()
    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.01)

    await queue.enqueue_user_message(
        UserMessageCommand(
            source="api",
            user_id="user-1",
            session_id="session-old",
            turn_id="turn-old",
            message="finish dispatch before clear",
        )
    )
    real_claim_next = queue.claim_next
    command_claimed = asyncio.Event()
    release_claim = asyncio.Event()
    clear_entered = asyncio.Event()

    async def _claim_then_pause(**kwargs):  # type: ignore[no-untyped-def]
        command = await real_claim_next(**kwargs)
        command_claimed.set()
        await release_claim.wait()
        return command

    monkeypatch.setattr(queue, "claim_next", _claim_then_pause)
    dispatch_task = asyncio.create_task(
        processor._run_next_command(queue=queue, message_bus=message_bus)
    )
    clear_task: asyncio.Task[tuple[int, int]] | None = None

    async def _clear() -> tuple[int, int]:
        async with queue.user_message_global_clear_boundary():
            clear_entered.set()
            return await queue.advance_user_message_generation_and_purge()

    try:
        await asyncio.wait_for(command_claimed.wait(), timeout=1)
        clear_task = asyncio.create_task(_clear())
        await asyncio.sleep(0.02)
        assert clear_entered.is_set() is False

        release_claim.set()
        await asyncio.wait_for(dispatch_task, timeout=1)
        assert await asyncio.wait_for(clear_task, timeout=1) == (1, 1)
        batch = await source_hub.get_batch(timeout_seconds=0.05)
        assert len(batch) == 1
        assert batch[0].payload["content"] == "finish dispatch before clear"
        assert processor._active_commands == 0
    finally:
        release_claim.set()
        if clear_task is not None:
            await asyncio.gather(clear_task, return_exceptions=True)
        if not dispatch_task.done():
            dispatch_task.cancel()
        await asyncio.gather(dispatch_task, return_exceptions=True)
        await source_hub.stop()
        await message_bus.stop()
        await queue.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("command_kind", ["source_sync", "source_state_flush"])
async def test_global_clear_waits_for_active_source_command(
    tmp_path: Path,
    command_kind: str,
) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    context = RuntimeBootstrapContext()
    command_started = asyncio.Event()
    release_command = asyncio.Event()
    clear_entered = asyncio.Event()
    order: list[str] = []

    class _BlockingSourceScheduler:
        async def queue_manual_sync(self, source_name: str, **kwargs):  # type: ignore[no-untyped-def]
            _ = (source_name, kwargs)
            command_started.set()
            await release_command.wait()
            order.append("source_write")

    class _BlockingSourceExecutor:
        async def flush_source_state(self, source_name: str, *, connection_id: str) -> None:
            assert connection_id == "account-main"
            _ = source_name
            command_started.set()
            await release_command.wait()
            order.append("source_write")

    context.agent_runtime.source_scheduler_contrib = _BlockingSourceScheduler()
    context.agent_runtime.source_sync_executor = _BlockingSourceExecutor()
    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.01)

    if command_kind == "source_sync":
        await queue.enqueue_source_sync(
            SourceSyncCommand(
                source="api",
                connection_id="account-main",
                source_name="chrome_history",
                sync_mode="backfill",
            )
        )
    else:
        await queue.enqueue_source_state_flush(
            SourceStateFlushCommand(source="api", connection_id="account-main", source_name="screen_time")
        )

    processing = asyncio.create_task(
        processor._run_next_command(queue=queue, message_bus=object())
    )

    async def _clear() -> tuple[int, int]:
        async with queue.user_message_global_clear_boundary():
            clear_entered.set()
            order.append("clear")
            return await queue.advance_user_message_generation_and_purge()

    clearing: asyncio.Task[tuple[int, int]] | None = None
    try:
        await asyncio.wait_for(command_started.wait(), timeout=1)
        clearing = asyncio.create_task(_clear())
        await asyncio.sleep(0.02)

        assert clear_entered.is_set() is False

        release_command.set()
        await asyncio.wait_for(processing, timeout=1)
        assert await asyncio.wait_for(clearing, timeout=1) == (1, 1)
        assert order == ["source_write", "clear"]
    finally:
        release_command.set()
        if clearing is not None:
            await asyncio.gather(clearing, return_exceptions=True)
        if not processing.done():
            processing.cancel()
        await asyncio.gather(processing, return_exceptions=True)
        await queue.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("command_kind", ["source_sync", "source_state_flush"])
async def test_source_command_queued_before_clear_cannot_run_after_clear(
    tmp_path: Path,
    command_kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    processor = RuntimeCommandProcessorModule(
        RuntimeBootstrapContext(),
        poll_interval_seconds=0.01,
    )
    executed: list[RuntimeCommandType] = []

    async def _record_execution(command, message_bus):  # type: ignore[no-untyped-def]
        _ = message_bus
        executed.append(command.command_type)
        return True

    monkeypatch.setattr(processor, "_execute_runtime_command", _record_execution)
    if command_kind == "source_sync":
        await queue.enqueue_source_sync(
            SourceSyncCommand(
                source="api",
                connection_id="account-main",
                source_name="chrome_history",
                sync_mode="backfill",
            )
        )
    else:
        await queue.enqueue_source_state_flush(
            SourceStateFlushCommand(source="api", connection_id="account-main", source_name="screen_time")
        )

    processing: asyncio.Task[None] | None = None
    try:
        async with queue.user_message_global_clear_boundary():
            processing = asyncio.create_task(
                processor._run_next_command(queue=queue, message_bus=object())
            )
            await asyncio.sleep(0.02)
            assert executed == []
            generation, purged = await queue.advance_user_message_generation_and_purge()
            assert generation == 1
            assert purged == 1

        assert processing is not None
        await asyncio.wait_for(processing, timeout=1)
        assert executed == []
    finally:
        if processing is not None and not processing.done():
            processing.cancel()
            await asyncio.gather(processing, return_exceptions=True)
        await queue.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command_type",
    [
        RuntimeCommandType.USER_MESSAGE,
        RuntimeCommandType.SOURCE_SYNC,
        RuntimeCommandType.SOURCE_STATE_FLUSH,
    ],
)
async def test_processor_rejects_stale_clear_sensitive_command(
    tmp_path: Path,
    command_type: RuntimeCommandType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    async with queue.user_message_global_clear_boundary():
        generation, purged = await queue.advance_user_message_generation_and_purge()
    assert (generation, purged) == (1, 0)

    processor = RuntimeCommandProcessorModule(RuntimeBootstrapContext())
    executed: list[RuntimeCommandType] = []

    async def _record_execution(command, message_bus):  # type: ignore[no-untyped-def]
        _ = message_bus
        executed.append(command.command_type)
        return True

    monkeypatch.setattr(processor, "_execute_runtime_command", _record_execution)
    stale_command = RuntimeQueuedCommand(
        command_id=999,
        command_type=command_type,
        payload={},
        correlation_id="stale-command",
        user_message_generation=0,
    )

    try:
        await processor._execute_admitted_command(
            queue=queue,
            command=stale_command,
            message_bus=object(),
        )
        assert executed == []
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_claimed_user_message_is_discarded_when_its_session_is_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    message_bus = await _start_in_memory_message_bus()
    source_hub = SourceHub(message_bus=message_bus)
    await source_hub.start()

    context = RuntimeBootstrapContext()
    context.runtime_commands.runtime_command_queue = queue
    context.message_bus.message_bus = message_bus
    context.agent_runtime.agent_runtime = object()
    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.01)

    await queue.enqueue_user_message(
        UserMessageCommand(
            source="api",
            user_id="user-1",
            session_id="session-delete",
            turn_id="turn-delete",
            message="must not dispatch after session delete",
            correlation_id="user_message:message-delete",
        )
    )
    real_claim_next = queue.claim_next
    command_claimed = asyncio.Event()
    release_claim = asyncio.Event()

    async def _claim_then_pause(**kwargs):  # type: ignore[no-untyped-def]
        command = await real_claim_next(**kwargs)
        command_claimed.set()
        await release_claim.wait()
        return command

    monkeypatch.setattr(queue, "claim_next", _claim_then_pause)
    dispatch_task = asyncio.create_task(
        processor._run_next_command(queue=queue, message_bus=message_bus)
    )
    try:
        await asyncio.wait_for(command_claimed.wait(), timeout=1)
        async with queue.user_message_clear_boundary():
            purged = await queue.block_user_message_scope_and_purge(
                user_id="user-1",
                session_id="session-delete",
                reason="user_delete_chat_session",
            )
        assert purged == 1

        release_claim.set()
        await asyncio.wait_for(dispatch_task, timeout=1)
        assert await source_hub.get_batch(timeout_seconds=0.05) == []
        assert processor._active_commands == 0
    finally:
        release_claim.set()
        if not dispatch_task.done():
            dispatch_task.cancel()
            await asyncio.gather(dispatch_task, return_exceptions=True)
        await source_hub.stop()
        await message_bus.stop()
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_processor_stays_non_idle_until_all_concurrent_work_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    context = RuntimeBootstrapContext()
    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.01)

    await queue.enqueue_refresh_llm_config(RefreshLLMConfigCommand(source="api", reason="first"))
    await queue.enqueue_refresh_llm_config(RefreshLLMConfigCommand(source="api", reason="second"))

    releases = [asyncio.Event(), asyncio.Event()]
    both_started = asyncio.Event()
    execution_count = 0

    async def _execute_and_wait(command, message_bus):  # type: ignore[no-untyped-def]
        nonlocal execution_count
        _ = (command, message_bus)
        index = execution_count
        execution_count += 1
        if execution_count == 2:
            both_started.set()
        await releases[index].wait()
        return True

    monkeypatch.setattr(processor, "_execute_runtime_command", _execute_and_wait)
    tasks = [
        asyncio.create_task(processor._run_next_command(queue=queue, message_bus=object()))
        for _ in range(2)
    ]
    try:
        await asyncio.wait_for(both_started.wait(), timeout=1)
        assert processor._active_commands == 2

        releases[0].set()
        done, _ = await asyncio.wait(tasks, timeout=1, return_when=asyncio.FIRST_COMPLETED)
        assert len(done) == 1
        assert processor._active_commands == 1
        with pytest.raises(asyncio.TimeoutError):
            await processor.wait_until_idle(timeout_seconds=0.01)

        releases[1].set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)
        await processor.wait_until_idle(timeout_seconds=0.1)
        assert processor._active_commands == 0
    finally:
        for release in releases:
            release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await queue.stop()


@pytest.mark.asyncio
async def test_runtime_command_processor_requeues_handler_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    await queue.enqueue_refresh_llm_config(
        RefreshLLMConfigCommand(source="api", reason="retry failure")
    )
    processor = RuntimeCommandProcessorModule(RuntimeBootstrapContext())

    async def _fail(command, message_bus):  # type: ignore[no-untyped-def]
        _ = (command, message_bus)
        raise RuntimeError("handler failed")

    monkeypatch.setattr(processor, "_execute_runtime_command", _fail)
    try:
        with pytest.raises(RuntimeError, match="handler failed"):
            await processor._run_next_command(queue=queue, message_bus=object())

        stats = await queue.get_stats()
        assert stats["pending_count"] == 1
        assert stats["claimed_count"] == 0
        assert processor._active_commands == 0
        await processor.wait_until_idle(timeout_seconds=0.1)
    finally:
        await queue.stop()
