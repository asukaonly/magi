import asyncio

try:
    import pytest
except ModuleNotFoundError:  # pragma: no cover
    class _Mark:
        @staticmethod
        def asyncio(func):
            return func

    class _PytestFallback:
        mark = _Mark()

    pytest = _PytestFallback()

from magi.core.runtime import (
    AgentRegistry,
    FactStore,
    RouterAgent,
    SensorHub,
    CHAT_AGENT_ID,
    MEMORY_DIGEST_AGENT_ID,
)
from magi.core.runtime.agents.base_runner import BaseRuntimeAgentRunner
from magi.events.events import Event, EventLevel, EventTypes
from magi.events.memory_backend import MemoryMessageBackend


class _NoopRunner(BaseRuntimeAgentRunner):
    async def handle_fact(self, fact):
        return None


@pytest.mark.asyncio
async def test_router_agent_loop_dispatches_batch_to_targets():
    message_bus = MemoryMessageBackend()
    await message_bus.start()

    sensor_hub = SensorHub(message_bus=message_bus)
    fact_store = FactStore()
    registry = AgentRegistry()
    registry.register_runner(_NoopRunner(CHAT_AGENT_ID))
    registry.register_runner(_NoopRunner(MEMORY_DIGEST_AGENT_ID))
    router_agent = RouterAgent(
        sensor_hub=sensor_hub,
        agent_registry=registry,
        fact_store=fact_store,
        batch_size=8,
        poll_timeout_seconds=0.1,
    )

    await sensor_hub.start()
    await router_agent.start()

    await message_bus.publish(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={"message": "hello", "user_id": "u1", "session_id": "s1"},
            source="test",
            level=EventLevel.INFO,
        )
    )

    await asyncio.sleep(0.3)
    await router_agent.stop()
    await sensor_hub.stop()
    await message_bus.stop()

    counts = fact_store.get_counts()
    assert counts.get(CHAT_AGENT_ID, 0) >= 1
    assert counts.get(MEMORY_DIGEST_AGENT_ID, 0) >= 1
