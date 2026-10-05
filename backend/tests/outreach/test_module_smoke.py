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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unavailable",
    [
        "runtime_agent_core",
        "runtime_channels",
        "runtime_scheduler",
        "runtime_chat_store",
        "runtime_personality",
    ],
)
async def test_outreach_initializes_only_after_every_runtime_dependency_is_ready(
    monkeypatch, unavailable
):
    from unittest.mock import AsyncMock, Mock
    from magi.bootstrap.lifecycle import (
        LifecycleInitDeferred,
        LifecycleModule,
        ModuleLifecycleOrchestrator,
    )

    names = [
        "runtime_agent_core",
        "runtime_channels",
        "runtime_scheduler",
        "runtime_chat_store",
        "runtime_personality",
    ]
    ready = False

    async def initialize_dependency():
        if not ready:
            raise LifecycleInitDeferred("Dependency is not ready")

    channel = SimpleNamespace(
        channel_registry=object(), session_mapper=object(), receipts_store=object()
    )
    ctx = SimpleNamespace(
        runtime_commands=SimpleNamespace(full_clear_recovery_pending=False),
        channels=SimpleNamespace(module=channel),
        chat=SimpleNamespace(store=object()),
        scheduler=SimpleNamespace(scheduler_service=object()),
        agent_runtime=SimpleNamespace(background_task_manager=object()),
        outreach=SimpleNamespace(service=None),
    )
    module = OutreachModule(ctx)
    service = object()
    build = Mock(return_value=service)
    register = AsyncMock()
    drain = AsyncMock()
    monkeypatch.setattr(module, "_build_service", build)
    monkeypatch.setattr(module, "_register_background_completion", register)
    monkeypatch.setattr(module, "_register_outbox_drain", drain)
    modules = [
        LifecycleModule(name, init=initialize_dependency if name == unavailable else None)
        for name in names
    ]
    lifecycle = ModuleLifecycleOrchestrator([module, *modules])
    await lifecycle.startup()
    assert not lifecycle.is_ready("runtime_outreach")
    assert lifecycle.snapshot()["runtime_outreach"]["blocked_by"] == [unavailable]
    assert ctx.outreach.service is None
    build.assert_not_called()
    ready = True
    await lifecycle.startup()
    assert lifecycle.is_ready("runtime_outreach")
    assert ctx.outreach.service is service
    build.assert_called_once()
    assert build.call_args.args[0] is ctx.chat.store
    assert build.call_args.args[1].receipts_store is channel.receipts_store
    register.assert_awaited_once_with(ctx.agent_runtime.background_task_manager, service)
    drain.assert_awaited_once_with(ctx.scheduler.scheduler_service, service, None)


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
        receipts_store=object(),
        channel_registry=_Registry(old_channel),
        session_mapper=_Mapper("old-mapping"),
    )
    context = SimpleNamespace(
        channels=SimpleNamespace(module=channel_module),
    )
    dependencies = OutreachModule._channel_deps(context)
    assert dependencies.module is channel_module
    assert dependencies.receipts_store is channel_module.receipts_store
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
