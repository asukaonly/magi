"""Tests for ChannelsModule lifecycle (Phase G+1, Task 5).

Verifies:
- ChatSseChannel is always registered under the "chat_sse" key,
  even when no plugin channels are loaded.
- NotificationRelay is no longer instantiated or started by
  ``_start_channels`` (Phase G+1 retires the polling relay path —
  delivery flows through DeliveryRouter on the write path now).
- Plugin-supplied channels keep working alongside chat_sse.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from _shared.db_schema import apply_chain_schema
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.agent.background import (
    BackgroundTask,
    BackgroundTaskEvent,
    BackgroundTaskManager,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskStore,
    BackgroundTaskTriggerSource,
)
from magi.agent.background.executor import BackgroundTaskRunResult
from magi.agent.cancel import CancelToken
from magi.channels.chat_sse_channel import ChatSseChannel
from magi.channels.lifecycle import ChannelsModule
from magi.channels.session_mapper import ChannelSessionMapper
from magi.chat.read_service import ChatReadService
from magi.events.runtime_queue import SQLiteRuntimeCommandQueue
from magi.utils.runtime import RuntimePaths
from magi_plugin_sdk.channels import (
    Channel,
    ChannelInboundClearStrategy,
    ChannelInboundClearRequest,
    ChannelTarget,
    OutboundContent,
)


# ---------------------------------------------------------------------------
# Minimal stubs (mimic only what ChannelsModule._start_channels reads)
# ---------------------------------------------------------------------------


class _FakePlugin:
    def __init__(self, channel: Channel | None) -> None:
        self._channel = channel

    def get_channel(self) -> Channel | None:
        return self._channel


class _FakePluginManager:
    def __init__(self, channels: list[Channel]) -> None:
        self._plugins = [_FakePlugin(ch) for ch in channels]

    def iter_loaded_plugins(self) -> list[_FakePlugin]:
        return list(self._plugins)


class _StubSessionProvisioner:
    async def create_channel_session(self, **kwargs):  # type: ignore[no-untyped-def]
        return "chsess_lifecycle_test"


class _StubAttachmentStore:
    async def store_attachment(self, **kwargs):  # type: ignore[no-untyped-def]
        return {}


class _AllowingBoundary:
    @asynccontextmanager
    async def operation(self, _context, **_kwargs):
        yield


class _NoPendingChatClearReadService:
    async def aget_interrupted_global_clear_count(self):
        return None


@pytest.fixture(autouse=True)
def _bind_chat_read_service(monkeypatch):
    monkeypatch.setattr(
        "magi.channels.lifecycle.require_chat_read_service",
        lambda: _NoPendingChatClearReadService(),
    )


def _build_ctx(*, plugins: list[Channel], tmp_path: Path) -> RuntimeBootstrapContext:
    """Build a minimally-populated RuntimeBootstrapContext sufficient for
    ``ChannelsModule._start_channels`` to execute."""
    from magi.runtime_trace import RuntimeTraceStore

    ctx = RuntimeBootstrapContext()
    ctx.plugins.plugin_manager = _FakePluginManager(plugins)  # type: ignore[assignment]
    ctx.core.runtime_paths = RuntimePaths(base_dir=tmp_path)
    ctx.runtime_commands.runtime_command_queue = SQLiteRuntimeCommandQueue(
        db_path=str(ctx.core.runtime_paths.message_queue_db_path)
    )
    ctx.chat.channel_session_provisioner = _StubSessionProvisioner()
    ctx.chat.channel_attachment_store = _StubAttachmentStore()
    # Real RuntimeTraceStore — ChannelsModule passes it to ChatSseChannel,
    # which only needs an object exposing ``append_notification``.
    ctx.runtime_trace.store = RuntimeTraceStore(db_path=str(tmp_path / "trace.db"))
    return ctx


class _FakePluginChannel(Channel):
    """Plugin-side channel that fully implements the Channel ABC."""

    inbound_clear_strategy = ChannelInboundClearStrategy.PROVIDER_TIME

    def __init__(self) -> None:
        self.clear_generations: list[int] = []

    @property
    def channel_type(self) -> str:
        return "fake_plugin"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send_message(
        self, target: ChannelTarget, content: OutboundContent
    ) -> None:
        return None

    async def send_typing_indicator(self, target: ChannelTarget) -> None:
        return None

    def bind_session_mapper(self, mapper) -> None:  # type: ignore[override]
        return None

    def bind_message_dispatcher(self, dispatcher) -> None:  # type: ignore[override]
        return None

    def bind_attachment_store(self, attachment_store) -> None:  # type: ignore[override]
        return None

    @asynccontextmanager
    async def inbound_clear_boundary(
        self,
        request: ChannelInboundClearRequest,
    ):
        self.clear_generations.append(request.clear_generation)
        yield


class _CursorPluginChannel(_FakePluginChannel):
    inbound_clear_strategy = ChannelInboundClearStrategy.DURABLE_CURSOR

    def __init__(self, events: list[str], *, fail_clear: bool = False) -> None:
        self._events = events
        self._fail_clear = fail_clear

    @property
    def channel_type(self) -> str:
        return "cursor_plugin"

    async def start(self) -> None:
        self._events.append("channel-started")

    @asynccontextmanager
    async def inbound_clear_boundary(
        self,
        request: ChannelInboundClearRequest,
    ):
        self._events.append(f"cursor-enter:{request.clear_generation}")
        if self._fail_clear:
            raise OSError("cursor persistence failed")
        try:
            yield
        finally:
            self._events.append("cursor-exit")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channels_module_registers_chat_sse_under_scheme_key(tmp_path):
    ctx = _build_ctx(plugins=[], tmp_path=tmp_path)
    module = ChannelsModule(ctx)
    try:
        await module._start_channels()
        assert module._registry is not None
        ch = module._registry.get("chat_sse")
        assert ch is not None
        assert isinstance(ch, ChatSseChannel)
    finally:
        await module._stop_channels()


@pytest.mark.asyncio
async def test_channels_module_does_not_start_notification_relay(tmp_path):
    ctx = _build_ctx(plugins=[], tmp_path=tmp_path)
    module = ChannelsModule(ctx)
    try:
        await module._start_channels()
        assert module._relay is None
        assert module._relay_task is None
    finally:
        await module._stop_channels()


@pytest.mark.asyncio
async def test_channels_module_starts_with_plugin_channels_plus_chat_sse(tmp_path):
    plugin_channel = _FakePluginChannel()
    ctx = _build_ctx(plugins=[plugin_channel], tmp_path=tmp_path)
    module = ChannelsModule(ctx)
    try:
        await module._start_channels()
        assert module._registry is not None
        assert module._registry.get("fake_plugin") is plugin_channel
        assert isinstance(module._registry.get("chat_sse"), ChatSseChannel)
    finally:
        await module._stop_channels()


@pytest.mark.asyncio
async def test_conversation_clear_advances_cursor_channel_before_body(tmp_path):
    from magi.channels.registry import ChannelRegistry

    events: list[str] = []
    registry = ChannelRegistry()
    registry.register(_CursorPluginChannel(events))
    provider_channel = _FakePluginChannel()
    registry.register(provider_channel)
    context = _build_ctx(plugins=[], tmp_path=tmp_path)
    context.runtime_commands.runtime_command_queue.read_current_clear_generation = (
        AsyncMock(return_value=4)
    )
    module = ChannelsModule(context)
    module._registry = registry

    async with module.conversation_clear_boundary():
        events.append("chat-clear")

    assert events == ["cursor-enter:4", "chat-clear", "cursor-exit"]
    assert provider_channel.clear_generations == [4]


@pytest.mark.asyncio
async def test_conversation_clear_fails_closed_when_cursor_cannot_advance(tmp_path):
    from magi.channels.registry import ChannelRegistry

    events: list[str] = []
    registry = ChannelRegistry()
    registry.register(_CursorPluginChannel(events, fail_clear=True))
    context = _build_ctx(plugins=[], tmp_path=tmp_path)
    context.runtime_commands.runtime_command_queue.read_current_clear_generation = (
        AsyncMock(return_value=4)
    )
    module = ChannelsModule(context)
    module._registry = registry

    with pytest.raises(OSError, match="cursor persistence failed"):
        async with module.conversation_clear_boundary():
            events.append("chat-clear")

    assert events == ["cursor-enter:4"]


@pytest.mark.asyncio
async def test_cursor_channel_reconciles_generation_before_polling_starts(tmp_path):
    events: list[str] = []
    cursor_channel = _CursorPluginChannel(events)
    ctx = _build_ctx(plugins=[cursor_channel], tmp_path=tmp_path)
    queue = ctx.runtime_commands.runtime_command_queue
    assert queue is not None
    await queue.start()
    async with queue.user_message_global_clear_boundary():
        await queue.advance_user_message_generation_and_purge()
    module = ChannelsModule(ctx)
    try:
        await module._start_channels()
        assert events[:3] == ["cursor-enter:1", "cursor-exit", "channel-started"]
    finally:
        await module._stop_channels()
        await queue.stop()


@pytest.mark.asyncio
async def test_failed_local_clear_disables_only_that_channel_at_startup(tmp_path):
    events: list[str] = []
    failing_channel = _CursorPluginChannel(events, fail_clear=True)
    healthy_channel = _FakePluginChannel()
    ctx = _build_ctx(
        plugins=[failing_channel, healthy_channel],
        tmp_path=tmp_path,
    )
    queue = ctx.runtime_commands.runtime_command_queue
    assert queue is not None
    await queue.start()
    async with queue.user_message_global_clear_boundary():
        await queue.advance_user_message_generation_and_purge()
    module = ChannelsModule(ctx)
    try:
        await module._start_channels()
        assert events == ["cursor-enter:1"]
        assert healthy_channel.clear_generations == [1]
        assert module._registry is not None
        assert isinstance(module._registry.get("chat_sse"), ChatSseChannel)
    finally:
        await module._stop_channels()
        await queue.stop()


@pytest.mark.asyncio
async def test_channels_module_exposes_delivery_receipts_store(tmp_path):
    ctx = _build_ctx(plugins=[], tmp_path=tmp_path)
    module = ChannelsModule(ctx)
    try:
        await module._start_channels()
        from magi.channels.receipts_store import DeliveryReceiptsStore
        assert isinstance(module._receipts_store, DeliveryReceiptsStore)
    finally:
        await module._stop_channels()


@pytest.mark.asyncio
async def test_channels_startup_recovers_pending_conversation_clear_before_starting(
    tmp_path,
    monkeypatch,
):
    events: list[str] = []

    class _ChatReadService:
        async def aget_interrupted_global_clear_count(self):
            events.append("clear-checked")
            return 2

        async def acomplete_global_clear(self):
            events.append("clear-finalized")
            return True

    class _SessionMapper:
        async def clear_conversation_state(self):
            events.append("channel-state-cleared")

    class _Registry:
        def all_channels(self):
            return []

        async def start_all(self, **_kwargs):
            events.append("registry-started")

    class _BackgroundTaskManager:
        @asynccontextmanager
        async def conversation_scope_boundary(self, **kwargs):
            assert kwargs == {"reason": "recover_global_conversation_clear"}
            events.append("background-sealed")
            try:
                yield
            finally:
                events.append("background-released")

        async def clear_all_history(self):
            events.append("background-history-cleared")

    monkeypatch.setattr(
        "magi.channels.lifecycle.require_chat_read_service",
        lambda: _ChatReadService(),
    )
    ctx = _build_ctx(plugins=[], tmp_path=tmp_path)
    ctx.agent_runtime.background_task_manager = _BackgroundTaskManager()
    module = ChannelsModule(ctx)
    startup = SimpleNamespace(
        registry=_Registry(),
        session_mapper=_SessionMapper(),
        binding_settings_store=None,
        cp_wiring=None,
        plugin_channel_count=0,
    )

    async def _prepare_channel_startup(*, deps, channel_instances):
        del deps, channel_instances
        return startup

    monkeypatch.setattr(module, "_prepare_channel_startup", _prepare_channel_startup)
    monkeypatch.setattr(
        module,
        "_activate_channel_runtime",
        lambda _startup: events.append("runtime-activated"),
    )
    monkeypatch.setattr(
        module,
        "_wire_control_fanout_if_available",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(module, "_log_channels_started", lambda **_kwargs: None)

    await module._start_channels()

    assert events == [
        "clear-checked",
        "background-sealed",
        "channel-state-cleared",
        "background-history-cleared",
        "clear-finalized",
        "background-released",
        "registry-started",
        "runtime-activated",
    ]


@pytest.mark.asyncio
async def test_channels_startup_stays_closed_when_pending_clear_cannot_finalize(
    tmp_path,
    monkeypatch,
):
    events: list[str] = []

    class _ChatReadService:
        async def aget_interrupted_global_clear_count(self):
            return 1

        async def acomplete_global_clear(self):
            events.append("clear-finalization-declined")
            return False

    class _SessionMapper:
        async def clear_conversation_state(self):
            events.append("channel-state-cleared")

    class _Registry:
        def all_channels(self):
            return []

        async def start_all(self, **_kwargs):
            events.append("registry-started")

    class _BackgroundTaskManager:
        @asynccontextmanager
        async def conversation_scope_boundary(self, **_kwargs):
            events.append("background-sealed")
            try:
                yield
            finally:
                events.append("background-released")

        async def clear_all_history(self):
            events.append("background-history-cleared")

    monkeypatch.setattr(
        "magi.channels.lifecycle.require_chat_read_service",
        lambda: _ChatReadService(),
    )
    ctx = _build_ctx(plugins=[], tmp_path=tmp_path)
    ctx.agent_runtime.background_task_manager = _BackgroundTaskManager()
    module = ChannelsModule(ctx)
    startup = SimpleNamespace(
        registry=_Registry(),
        session_mapper=_SessionMapper(),
        binding_settings_store=None,
        cp_wiring=None,
        plugin_channel_count=0,
    )

    async def _prepare_channel_startup(*, deps, channel_instances):
        del deps, channel_instances
        return startup

    monkeypatch.setattr(module, "_prepare_channel_startup", _prepare_channel_startup)

    with pytest.raises(
        RuntimeError,
        match="could not be completed",
    ):
        await module._start_channels()

    assert events == [
        "background-sealed",
        "channel-state-cleared",
        "background-history-cleared",
        "clear-finalization-declined",
        "background-released",
    ]


@pytest.mark.asyncio
async def test_pending_global_clear_recovery_closes_real_chat_and_channel_stores(
    tmp_path,
    monkeypatch,
):
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    apply_chain_schema("chat", runtime_paths.chat_db_path)
    apply_chain_schema("channels", runtime_paths.channels_db_path)
    apply_chain_schema("background_tasks", runtime_paths.background_tasks_db_path)
    chat_read_service = ChatReadService(runtime_paths=runtime_paths)
    chat_connection = chat_read_service._get_conn()
    chat_connection.execute(
        """
        INSERT INTO chat_sessions(
            session_id, user_id, title, created_at_ms, updated_at_ms
        ) VALUES ('session-before-clear', 'local_user', 'Old chat', 1, 1)
        """
    )
    chat_connection.commit()
    assert chat_read_service.clear_all_sessions() == 1
    assert chat_read_service.get_interrupted_global_clear_count() == 1

    with sqlite3.connect(runtime_paths.channels_db_path) as channel_connection:
        channel_connection.execute(
            """
            INSERT INTO channel_session_mappings(
                channel_type,
                external_chat_id,
                magi_session_id,
                magi_user_id,
                is_group,
                created_at_ms,
                last_active_at_ms,
                metadata_json
            ) VALUES ('telegram', 'chat-1', 'session-before-clear',
                      'local_user', 0, 1, 1, '{}')
            """
        )
        channel_connection.execute(
            """
            INSERT INTO outreach_outbox(
                correlation_id,
                channel_scope,
                intent_fingerprint,
                intent_json,
                release_at_ms,
                status,
                created_at_ms
            ) VALUES ('task:attempt:0', 'telegram', 'fingerprint',
                      '{}', 1, 'pending', 1)
            """
        )
        channel_connection.commit()

    mapper = ChannelSessionMapper(
        db_path=str(runtime_paths.channels_db_path),
        session_provisioner=_StubSessionProvisioner(),
        ingress_boundary=_AllowingBoundary(),  # type: ignore[arg-type]
    )
    await mapper.initialize()
    background_store = BackgroundTaskStore(
        db_path=str(runtime_paths.background_tasks_db_path)
    )
    background_task = BackgroundTask.new(
        BackgroundTaskSpec(
            user_id="local_user",
            session_id="session-before-clear",
            origin_turn_id="turn-before-clear",
            title="Private task",
            goal="Private task goal",
            selected_tools=[],
            trigger_source=BackgroundTaskTriggerSource.PLANNER,
        )
    )
    await background_store.create_task(background_task)
    background_task.status = BackgroundTaskStatus.SUCCEEDED
    await background_store.persist_terminal_transition(
        background_task,
        BackgroundTaskEvent.transition(
            task_id=background_task.task_id,
            attempt_index=background_task.attempt_index,
            from_status=BackgroundTaskStatus.PENDING,
            to_status=BackgroundTaskStatus.SUCCEEDED,
        ),
    )

    async def run_fn(
        task: BackgroundTask,
        token: CancelToken,
    ) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult(summary="unused")

    background_manager = BackgroundTaskManager(
        store=background_store,
        run_fn=run_fn,
        max_concurrent=1,
    )
    await background_manager.start()
    monkeypatch.setattr(
        "magi.channels.lifecycle.require_chat_read_service",
        lambda: chat_read_service,
    )

    runtime_command_queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths.message_queue_db_path)
    )
    await runtime_command_queue.start()
    async with runtime_command_queue.user_message_clear_boundary():
        await runtime_command_queue.advance_user_message_generation_and_purge()
    with sqlite3.connect(runtime_paths.message_queue_db_path) as queue_connection:
        cutoff_before_recovery = float(
            queue_connection.execute(
                "SELECT updated_at FROM runtime_user_message_clear_state "
                "WHERE singleton_id = 1"
            ).fetchone()[0]
        )
    await asyncio.sleep(0.01)

    context = RuntimeBootstrapContext()
    context.agent_runtime.background_task_manager = background_manager
    context.runtime_commands.runtime_command_queue = runtime_command_queue
    try:
        await ChannelsModule(context)._recover_pending_conversation_clear(
            registry=SimpleNamespace(all_channels=lambda: []),
            session_mapper=mapper,
        )
    finally:
        await background_manager.stop()
        await runtime_command_queue.stop()

    assert chat_read_service.get_interrupted_global_clear_count() is None
    with sqlite3.connect(runtime_paths.channels_db_path) as channel_connection:
        assert channel_connection.execute(
            "SELECT COUNT(*) FROM channel_session_mappings"
        ).fetchone() == (0,)
        assert channel_connection.execute(
            "SELECT COUNT(*) FROM outreach_outbox"
        ).fetchone() == (0,)
    assert await background_store.get_task(background_task.task_id) is None
    assert await background_store.list_events(background_task.task_id) == []
    assert await background_store.count_pending_completion_intents() == 0
    with sqlite3.connect(runtime_paths.message_queue_db_path) as queue_connection:
        cutoff_after_recovery = float(
            queue_connection.execute(
                "SELECT updated_at FROM runtime_user_message_clear_state "
                "WHERE singleton_id = 1"
            ).fetchone()[0]
        )
    assert cutoff_after_recovery > cutoff_before_recovery
    chat_read_service.close()


@pytest.mark.asyncio
async def test_pending_global_clear_recovery_does_not_finalize_when_task_cleanup_fails(
    tmp_path,
    monkeypatch,
):
    finalize = AsyncMock(return_value=True)

    class _ChatReadService:
        async def aget_interrupted_global_clear_count(self):
            return 1

        acomplete_global_clear = finalize

    class _SessionMapper:
        clear_conversation_state = AsyncMock(return_value={})

    class _BackgroundTaskManager:
        @asynccontextmanager
        async def conversation_scope_boundary(self, **_kwargs):
            yield

        async def clear_all_history(self):
            raise OSError("background task database unavailable")

    monkeypatch.setattr(
        "magi.channels.lifecycle.require_chat_read_service",
        lambda: _ChatReadService(),
    )
    context = _build_ctx(plugins=[], tmp_path=tmp_path)
    context.agent_runtime.background_task_manager = _BackgroundTaskManager()

    with pytest.raises(OSError, match="background task database unavailable"):
        await ChannelsModule(context)._recover_pending_conversation_clear(
            registry=SimpleNamespace(all_channels=lambda: []),
            session_mapper=_SessionMapper(),
        )

    finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_delivery_boundary_rejects_pending_conversation_clear(
    tmp_path,
    monkeypatch,
):
    module = ChannelsModule(_build_ctx(plugins=[], tmp_path=tmp_path))
    monkeypatch.setattr(
        module,
        "_conversation_delivery_allowed",
        AsyncMock(return_value=False),
    )

    with pytest.raises(
        RuntimeError,
        match="blocked by a pending clear",
    ):
        async with module.external_delivery_boundary():
            pytest.fail("delivery boundary must not open")


@pytest.mark.asyncio
async def test_channel_restart_waits_for_active_external_delivery(
    tmp_path,
    monkeypatch,
):
    module = ChannelsModule(_build_ctx(plugins=[], tmp_path=tmp_path))
    events: list[str] = []
    monkeypatch.setattr(
        module,
        "_conversation_delivery_allowed",
        AsyncMock(return_value=True),
    )

    async def _stop_channels():
        events.append("stopped")

    async def _start_channels():
        events.append("started")

    monkeypatch.setattr(module, "_stop_channels", _stop_channels)
    monkeypatch.setattr(module, "_start_channels", _start_channels)

    async with module.external_delivery_boundary():
        restart_task = asyncio.create_task(module.restart())
        await asyncio.sleep(0)
        assert events == []

    await restart_task
    assert events == ["stopped", "started"]


@pytest.mark.asyncio
async def test_channel_shutdown_waits_for_active_external_delivery(
    tmp_path,
    monkeypatch,
):
    context = _build_ctx(plugins=[], tmp_path=tmp_path)
    module = ChannelsModule(context)
    context.channels.module = module
    events: list[str] = []
    monkeypatch.setattr(
        module,
        "_conversation_delivery_allowed",
        AsyncMock(return_value=True),
    )

    async def _stop_channels():
        events.append("stopped")

    monkeypatch.setattr(module, "_stop_channels", _stop_channels)

    async with module.external_delivery_boundary():
        shutdown_task = asyncio.create_task(module.shutdown())
        await asyncio.sleep(0)
        assert events == []
        assert context.channels.module is module

    await shutdown_task
    assert events == ["stopped"]
    assert context.channels.module is None
