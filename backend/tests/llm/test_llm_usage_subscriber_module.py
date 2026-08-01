"""Phase 2 of D: LLMUsageSubscriberModule init/shutdown smoke."""

from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.llm.lifecycle import LLMUsageSubscriberModule


@pytest.mark.asyncio
async def test_module_init_starts_subscriber_when_store_ready():
    context = MagicMock()
    fake_bus = MagicMock()
    fake_bus.subscribe = AsyncMock(return_value="sub-id")
    fake_bus.unsubscribe = AsyncMock(return_value=True)
    fake_store = MagicMock()
    fake_store.record_call = AsyncMock()
    context.message_bus.message_bus = fake_bus
    context.llm.llm_usage_store = fake_store
    context.memory.unified_memory.memory_operation_epoch.return_value = 0
    context.runtime_commands.full_clear_recovery_pending = False

    module = LLMUsageSubscriberModule(context)
    await module.init()
    fake_bus.subscribe.assert_awaited_once()
    assert context.llm.llm_usage_subscriber is not None

    await module.shutdown()
    fake_bus.unsubscribe.assert_awaited_once()
    assert context.llm.llm_usage_subscriber is None


@pytest.mark.asyncio
async def test_module_init_idle_when_store_missing():
    context = MagicMock()
    fake_bus = MagicMock()
    fake_bus.subscribe = AsyncMock()
    context.message_bus.message_bus = fake_bus
    context.llm.llm_usage_store = None
    context.memory.unified_memory.memory_operation_epoch.return_value = 0
    context.runtime_commands.full_clear_recovery_pending = False

    module = LLMUsageSubscriberModule(context)
    await module.init()
    fake_bus.subscribe.assert_not_awaited()
    # shutdown is no-op when store missing
    await module.shutdown()


@pytest.mark.asyncio
async def test_module_init_stays_idle_during_full_clear_recovery():
    context = MagicMock()
    fake_bus = MagicMock()
    fake_bus.subscribe = AsyncMock()
    context.message_bus.message_bus = fake_bus
    context.llm.llm_usage_store = MagicMock()
    context.llm.llm_usage_subscriber = None
    context.memory.unified_memory.memory_operation_epoch.return_value = 0
    context.runtime_commands.full_clear_recovery_pending = True

    module = LLMUsageSubscriberModule(context)
    await module.init()

    fake_bus.subscribe.assert_not_awaited()
    assert context.llm.llm_usage_subscriber is None
    await module.shutdown()
