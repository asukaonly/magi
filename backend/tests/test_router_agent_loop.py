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
    RouterAgent,
    SensorHub,
    TaskAgent,
    TaskAgentManager,
    TaskAgentType,
)
from magi.events.events import Event, EventLevel, EventTypes
from magi.events.memory_backend import MemoryMessageBackend


class _NoopTaskAgent(TaskAgent):
    def __init__(self, agent_type: TaskAgentType, agent_id: str):
        super().__init__(agent_type=agent_type, agent_id=agent_id)

    async def handle_fact(self, fact):
        return None


@pytest.mark.asyncio
async def test_router_agent_loop_dispatches_batch_to_targets():
    message_bus = MemoryMessageBackend()
    await message_bus.start()

    sensor_hub = SensorHub(message_bus=message_bus)
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _NoopTaskAgent(TaskAgentType.CHAT, agent_id),
        create_memory_digest_agent=lambda agent_id: _NoopTaskAgent(TaskAgentType.MEMORY_DIGEST, agent_id),
        create_daily_report_agent=lambda agent_id: _NoopTaskAgent(TaskAgentType.DAILY_REPORT, agent_id),
    )
    await manager.start_all(action_executor=None)
    router_agent = RouterAgent(
        sensor_hub=sensor_hub,
        task_agent_manager=manager,
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

    await asyncio.sleep(0.5)
    router_stats = router_agent.get_stats()
    assert manager.get_agent(TaskAgentType.CHAT, "u1") is not None
    assert manager.get_agent(TaskAgentType.MEMORY_DIGEST, "default") is not None
    await router_agent.stop()
    await manager.stop_all()
    await sensor_hub.stop()
    await message_bus.stop()

    assert router_stats["facts_written"] >= 2
