from types import SimpleNamespace

import pytest

from magi.channels.delivery_router import DeliveryRouter
from magi.outreach.executor import ExternalChannelExecutor
from magi.outreach.lifecycle import (
    OutreachModule,
    _LiveChannelRegistry,
    _LiveChannelSessionMapper,
)
from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.delivery import DeliveryReceipt

from magi.outreach.contracts import OutreachIntent, OutreachKind


def test_module_declares_expected_dependencies():
    mod = OutreachModule(context=object())
    assert mod.name == "runtime_outreach"
    deps = set(mod.dependencies)
    assert {"runtime_agent_core", "runtime_channels", "runtime_scheduler",
            "runtime_chat_store", "runtime_personality"} <= deps


def test_module_uses_public_live_channel_dependencies():
    registry = object()
    mapper = object()
    receipts = object()
    channel_module = SimpleNamespace(
        channel_registry=registry,
        session_mapper=mapper,
        receipts_store=receipts,
    )
    context = SimpleNamespace(
        channels=SimpleNamespace(module=channel_module),
    )

    dependencies = OutreachModule._channel_deps(context)

    assert dependencies is not None
    assert dependencies.module is channel_module
    assert dependencies.receipts_store is receipts


@pytest.mark.asyncio
async def test_live_channel_dependencies_follow_runtime_restart():
    class _Channel:
        def __init__(self, name):
            self.name = name
            self.delivered = []

        async def deliver(self, target, content):
            self.delivered.append((target, content))
            return DeliveryReceipt(
                channel_id=self.name,
                external_message_id=f"{self.name}-message",
                delivered_at_ms=1,
            )

    class _Registry:
        def __init__(self, channel):
            self.channel = channel

        def get(self, channel_id):
            if channel_id == "telegram":
                return self.channel
            return None

    class _Mapper:
        def __init__(self, marker):
            self.marker = marker

        async def lookup_by_session(self, _session_id):
            return self.marker

    old_channel = _Channel("old")
    new_channel = _Channel("new")
    channel_module = SimpleNamespace(
        channel_registry=_Registry(old_channel),
        session_mapper=_Mapper("old-mapping"),
    )
    context = SimpleNamespace(
        channels=SimpleNamespace(module=channel_module),
    )
    live_registry = _LiveChannelRegistry(context)
    live_mapper = _LiveChannelSessionMapper(context)
    executor = ExternalChannelExecutor(
        delivery_router=DeliveryRouter(channel_registry=live_registry),
        receipts_store=None,
    )
    intent = OutreachIntent(
        kind=OutreachKind.TASK_COMPLETED,
        user_id="u1",
        origin_session_id="s1",
        title="Task",
        facts="Done",
        correlation_id="task:attempt:0",
        completed_at_ms=1,
    )
    target = ChannelTarget(
        channel_type="telegram",
        external_chat_id="",
        magi_session_id="s1",
        magi_user_id="u1",
    )

    await executor.push(intent, "first", target=target)
    assert await live_mapper.lookup_by_session("s1") == "old-mapping"

    channel_module.channel_registry = _Registry(new_channel)
    channel_module.session_mapper = _Mapper("new-mapping")

    await executor.push(intent, "second", target=target)

    assert len(old_channel.delivered) == 1
    assert len(new_channel.delivered) == 1
    assert new_channel.delivered[0][1].text == "second"
    assert await live_mapper.lookup_by_session("s1") == "new-mapping"
