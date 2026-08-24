"""Lifecycle wiring for the control transcript clear boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.chat.lifecycle import ControlTranscriptSubscriberModule
from magi.control.common import InteractionBroker
from magi.control.permission.brokered_prompter import PendingPermissionRegistry
from magi.control.session_store import ControlSessionStore
from magi.control.user_content_clear import ControlUserContentClearCoordinator


class _Bus:
    def __init__(self) -> None:
        self.subscriptions: set[str] = set()

    async def subscribe(self, event_type, callback):
        _ = callback
        subscription_id = f"{event_type}:{len(self.subscriptions)}"
        self.subscriptions.add(subscription_id)
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        self.subscriptions.discard(subscription_id)
        return True


@pytest.mark.asyncio
async def test_lifecycle_binds_and_unbinds_control_clear_coordinator() -> None:
    context = RuntimeBootstrapContext()
    bus = _Bus()
    memory = SimpleNamespace(memory_operation_epoch=lambda: 7)
    coordinator = ControlUserContentClearCoordinator(
        session_store=ControlSessionStore(),
        pending_permissions=PendingPermissionRegistry(),
        interaction_broker=InteractionBroker(),
    )
    context.message_bus.message_bus = bus
    context.memory.unified_memory = memory
    context.control_plane.module = SimpleNamespace(
        wiring=SimpleNamespace(user_content_clear=coordinator)
    )
    module = ControlTranscriptSubscriberModule(context)

    await module.init()
    subscriber = coordinator.transcript_subscriber
    assert subscriber is not None
    assert subscriber._memory_epoch_getter() == 7
    assert len(bus.subscriptions) == 3

    await module.shutdown()
    assert coordinator.transcript_subscriber is None
    assert bus.subscriptions == set()
