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

from magi.awareness.contracts import SensorEvent
from magi.awareness.sensor_hub import SensorHub
from magi.agent.runtime import (
    RouterAgent,
    TaskAgent,
    TaskAgentManager,
    TaskAgentType,
)
from magi.events.events import Event, EventLevel, EventTypes
from magi.events.in_memory_backend import InMemoryMessageBusBackend


class _NoopTaskAgent(TaskAgent):
    def __init__(self, agent_type: TaskAgentType, agent_id: str):
        super().__init__(agent_type=agent_type, agent_id=agent_id)

    async def handle_fact(self, fact):
        return None


@pytest.mark.asyncio
async def test_router_agent_loop_dispatches_batch_to_targets(tmp_path):
    message_bus = InMemoryMessageBusBackend(num_workers=1)
    await message_bus.start()

    sensor_hub = SensorHub(message_bus=message_bus)
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _NoopTaskAgent(TaskAgentType.CHAT, agent_id),
    )
    await manager.start_all(event_emitter=None)
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
            data={"content": "hello", "user_id": "u1", "session_id": "s1"},
            source="test",
            level=EventLevel.INFO,
        )
    )

    await asyncio.sleep(0.5)
    router_stats = router_agent.get_stats()
    assert manager.get_agent(TaskAgentType.CHAT, "s1") is not None
    await router_agent.stop()
    await manager.stop_all()
    await sensor_hub.stop()
    await message_bus.stop()

    assert router_stats["facts_written"] >= 1


@pytest.mark.asyncio
async def test_router_agent_loop_routes_targeted_timeline_events(tmp_path):
    message_bus = InMemoryMessageBusBackend(num_workers=1)
    await message_bus.start()

    sensor_hub = SensorHub(message_bus=message_bus)
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _NoopTaskAgent(TaskAgentType.CHAT, agent_id),
        create_default_agent=lambda agent_type, agent_id: _NoopTaskAgent(agent_type, agent_id),
    )
    await manager.start_all(event_emitter=None)
    router_agent = RouterAgent(
        sensor_hub=sensor_hub,
        task_agent_manager=manager,
        batch_size=8,
        poll_timeout_seconds=0.1,
    )

    await sensor_hub.start()
    await router_agent.start()
    await sensor_hub.push_sensor_event(
        SensorEvent(
            sensor_name="timeline_sensor",
            event_type="TimelineSourceDetected",
            payload={
                "target_task_agent_type": TaskAgentType.TIMELINE.value,
                "target_task_agent_id": "timeline-main",
                "source_type": "photo_library",
            },
        )
    )

    await asyncio.sleep(0.5)
    router_stats = router_agent.get_stats()
    timeline_agent = manager.get_agent(TaskAgentType.TIMELINE, "timeline-main")

    await router_agent.stop()
    await manager.stop_all()
    await sensor_hub.stop()
    await message_bus.stop()

    assert timeline_agent is not None
    assert timeline_agent.get_stats()["processed"] >= 1
    assert router_stats["facts_written"] >= 1


@pytest.mark.asyncio
async def test_router_agent_propagates_user_message_delivery_identity():
    class _RecordingManager:
        def __init__(self):
            self.facts = []

        @staticmethod
        def resolve_targets(sensor_event):
            return [(TaskAgentType.CHAT, sensor_event.payload["session_id"])]

        async def add_fact_to_agent(self, agent_type, agent_id, fact):
            _ = (agent_type, agent_id)
            self.facts.append(fact)
            return True

    message_bus = InMemoryMessageBusBackend(num_workers=1)
    await message_bus.start()
    sensor_hub = SensorHub(message_bus=message_bus)
    manager = _RecordingManager()
    router_agent = RouterAgent(
        sensor_hub=sensor_hub,
        task_agent_manager=manager,
        batch_size=1,
        poll_timeout_seconds=0.01,
    )

    await router_agent.start()
    await sensor_hub.push_sensor_event(
        SensorEvent(
            sensor_name="user_input_sensor",
            event_type=EventTypes.USER_MESSAGE,
            payload={"session_id": "session-1", "content": "hello"},
            correlation_id="user_message:message-1",
            delivery_attempt_no=2,
            runtime_command_id=99,
        )
    )
    try:
        for _ in range(100):
            if manager.facts:
                break
            await asyncio.sleep(0.01)
    finally:
        await router_agent.stop()
        await message_bus.stop()

    assert len(manager.facts) == 1
    assert manager.facts[0].delivery_attempt_no == 2
    assert manager.facts[0].runtime_command_id == 99
