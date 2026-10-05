import asyncio

import pytest

from magi.awareness.contracts import SourceEvent
from magi.awareness.source_hub import SourceHub
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
async def test_router_agent_loop_delivers_each_fact_to_its_session():
    bus = InMemoryMessageBusBackend(num_workers=1)
    await bus.start()
    hub = SourceHub(message_bus=bus)
    processed = []
    completed = asyncio.Event()

    class RecordingAgent(TaskAgent):
        async def execute_request(self, context, request):
            processed.append((self.agent_id, context.latest_fact))
            if len(processed) == 2:
                completed.set()
            return {}

    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: RecordingAgent(
            agent_type=TaskAgentType.CHAT, agent_id=agent_id
        )
    )
    await manager.start_all(event_emitter=None)
    router = RouterAgent(
        source_hub=hub, task_agent_manager=manager, batch_size=8, poll_timeout_seconds=0.01
    )
    await hub.start()
    await router.start()
    try:
        for index in (1, 2):
            await bus.publish(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "content": f"message-{index}",
                        "user_id": f"u{index}",
                        "session_id": f"s{index}",
                        "turn_id": f"t{index}",
                    },
                    source="test",
                    level=EventLevel.INFO,
                )
            )
        await asyncio.wait_for(completed.wait(), timeout=2)
        await asyncio.wait_for(bus._queue.join(), timeout=2)
    finally:
        await router.stop()
        await manager.stop_all()
        await hub.stop()
        await bus.stop()
    actual = {}
    for agent_id, fact in processed:
        assert fact.event_type == EventTypes.USER_MESSAGE
        assert fact.agent_instance_id == agent_id
        assert fact.agent_type == TaskAgentType.CHAT.value
        actual[agent_id] = {
            key: fact.payload[key] for key in ("content", "user_id", "session_id", "turn_id")
        }
    assert actual == {
        f"s{i}": {
            "content": f"message-{i}",
            "user_id": f"u{i}",
            "session_id": f"s{i}",
            "turn_id": f"t{i}",
        }
        for i in (1, 2)
    }
    assert len(processed) == 2
    assert router.get_stats()["facts_written"] == 2


@pytest.mark.asyncio
async def test_router_agent_loop_routes_targeted_timeline_events(tmp_path):
    message_bus = InMemoryMessageBusBackend(num_workers=1)
    await message_bus.start()

    source_hub = SourceHub(message_bus=message_bus)
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _NoopTaskAgent(TaskAgentType.CHAT, agent_id),
        create_default_agent=lambda agent_type, agent_id: _NoopTaskAgent(agent_type, agent_id),
    )
    await manager.start_all(event_emitter=None)
    router_agent = RouterAgent(
        source_hub=source_hub,
        task_agent_manager=manager,
        batch_size=8,
        poll_timeout_seconds=0.1,
    )

    await source_hub.start()
    await router_agent.start()
    await source_hub.push_source_event(
        SourceEvent(
            source_name="timeline_source",
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
    await source_hub.stop()
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
        def resolve_targets(source_event):
            return [(TaskAgentType.CHAT, source_event.payload["session_id"])]

        async def add_fact_to_agent(self, agent_type, agent_id, fact):
            _ = (agent_type, agent_id)
            self.facts.append(fact)
            return True

    message_bus = InMemoryMessageBusBackend(num_workers=1)
    await message_bus.start()
    source_hub = SourceHub(message_bus=message_bus)
    manager = _RecordingManager()
    router_agent = RouterAgent(
        source_hub=source_hub,
        task_agent_manager=manager,
        batch_size=1,
        poll_timeout_seconds=0.01,
    )

    await router_agent.start()
    await source_hub.push_source_event(
        SourceEvent(
            source_name="user_input_source",
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
