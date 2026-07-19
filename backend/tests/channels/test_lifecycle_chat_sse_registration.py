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
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from _shared.db_schema import apply_chain_schema
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.channels.chat_sse_channel import ChatSseChannel
from magi.channels.lifecycle import ChannelsModule
from magi.channels.session_mapper import ChannelSessionMapper
from magi.chat.read_service import ChatReadService
from magi.utils.runtime import RuntimePaths
from magi_plugin_sdk.channels import Channel, ChannelTarget, OutboundContent


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
    ctx.chat.channel_session_provisioner = _StubSessionProvisioner()
    ctx.chat.channel_attachment_store = _StubAttachmentStore()
    # Real RuntimeTraceStore — ChannelsModule passes it to ChatSseChannel,
    # which only needs an object exposing ``append_notification``.
    ctx.runtime_trace.store = RuntimeTraceStore(db_path=str(tmp_path / "trace.db"))
    return ctx


class _FakePluginChannel(Channel):
    """Plugin-side channel that fully implements the Channel ABC."""

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

    class _OrchestrationStore:
        async def clear_all(self):
            events.append("orchestration-cleared")

    class _Registry:
        async def start_all(self):
            events.append("registry-started")

    monkeypatch.setattr(
        "magi.channels.lifecycle.require_chat_read_service",
        lambda: _ChatReadService(),
    )
    monkeypatch.setattr(
        "magi.agent.orchestration.get_orchestration_store",
        lambda: _OrchestrationStore(),
    )

    ctx = _build_ctx(plugins=[], tmp_path=tmp_path)
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
        "channel-state-cleared",
        "orchestration-cleared",
        "clear-finalized",
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

    class _OrchestrationStore:
        async def clear_all(self):
            events.append("orchestration-cleared")

    class _Registry:
        async def start_all(self):
            events.append("registry-started")

    monkeypatch.setattr(
        "magi.channels.lifecycle.require_chat_read_service",
        lambda: _ChatReadService(),
    )
    monkeypatch.setattr(
        "magi.agent.orchestration.get_orchestration_store",
        lambda: _OrchestrationStore(),
    )

    module = ChannelsModule(_build_ctx(plugins=[], tmp_path=tmp_path))
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
        "channel-state-cleared",
        "orchestration-cleared",
        "clear-finalization-declined",
    ]


@pytest.mark.asyncio
async def test_pending_global_clear_recovery_closes_real_chat_and_channel_stores(
    tmp_path,
    monkeypatch,
):
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    apply_chain_schema("chat", runtime_paths.chat_db_path)
    apply_chain_schema("channels", runtime_paths.channels_db_path)
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
    )
    await mapper.initialize()
    orchestration_store = SimpleNamespace(clear_all=AsyncMock(return_value={}))
    monkeypatch.setattr(
        "magi.channels.lifecycle.require_chat_read_service",
        lambda: chat_read_service,
    )
    monkeypatch.setattr(
        "magi.agent.orchestration.get_orchestration_store",
        lambda: orchestration_store,
    )

    await ChannelsModule(RuntimeBootstrapContext())._recover_pending_conversation_clear(
        mapper
    )

    assert chat_read_service.get_interrupted_global_clear_count() is None
    with sqlite3.connect(runtime_paths.channels_db_path) as channel_connection:
        assert channel_connection.execute(
            "SELECT COUNT(*) FROM channel_session_mappings"
        ).fetchone() == (0,)
        assert channel_connection.execute(
            "SELECT COUNT(*) FROM outreach_outbox"
        ).fetchone() == (0,)
    orchestration_store.clear_all.assert_awaited_once()
    chat_read_service.close()


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
