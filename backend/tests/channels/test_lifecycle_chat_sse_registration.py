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

from pathlib import Path

import pytest

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.channels.chat_sse_channel import ChatSseChannel
from magi.channels.lifecycle import ChannelsModule
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
