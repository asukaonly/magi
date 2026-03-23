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

from magi.agent.runtime import TaskAgent, TaskAgentManager, TaskAgentType
from magi.agent.task_agents import DefaultTaskAgent
from magi.agent.runtime.contracts import FactRecord
from magi.awareness.contracts import SensorEvent
from magi.events.events import EventTypes


class _CollectTaskAgent(TaskAgent):
    def __init__(self, agent_type: TaskAgentType, agent_id: str):
        super().__init__(agent_type=agent_type, agent_id=agent_id)
        self.collected = []

    async def handle_fact(self, fact: FactRecord) -> None:
        self.collected.append(fact)


@pytest.mark.asyncio
async def test_task_agent_manager_hybrid_creation_and_dispatch():
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _CollectTaskAgent(TaskAgentType.CHAT, agent_id),
    )
    await manager.start_all(action_emitter=None)

    # Core instances should exist.
    assert manager.get_agent(TaskAgentType.CHAT, "default") is not None

    # Dynamic instance should be created on demand.
    fact = FactRecord(
        agent_id="chat:u-chat",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id="u-chat",
        event_type="USER_MESSAGE",
        payload={"content": "hello"},
    )
    await manager.add_fact_to_agent(TaskAgentType.CHAT, "u-chat", fact)
    await asyncio.sleep(0.2)

    dynamic = manager.get_agent(TaskAgentType.CHAT, "u-chat")
    assert dynamic is not None
    assert dynamic.get_stats()["processed"] >= 1

    await manager.stop_all()


def test_task_agent_manager_routes_user_messages_by_session_id():
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _CollectTaskAgent(TaskAgentType.CHAT, agent_id),
    )

    targets = manager.resolve_targets(
        SensorEvent(
            sensor_name="user_input_sensor",
            event_type=EventTypes.USER_MESSAGE,
            payload={
                "content": "hello",
                "user_id": "u-chat",
                "session_id": "s-chat",
            },
        )
    )

    assert targets == [(TaskAgentType.CHAT, "s-chat")]


def test_task_agent_manager_rejects_user_messages_without_session_id():
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _CollectTaskAgent(TaskAgentType.CHAT, agent_id),
    )

    with pytest.raises(ValueError, match="session_id"):
        manager.resolve_targets(
            SensorEvent(
                sensor_name="user_input_sensor",
                event_type=EventTypes.USER_MESSAGE,
                payload={
                    "content": "hello",
                    "user_id": "u-chat",
                },
            )
        )


@pytest.mark.asyncio
async def test_task_agent_manager_supports_default_agent_type():
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _CollectTaskAgent(TaskAgentType.CHAT, agent_id),
        create_default_agent=lambda agent_type, agent_id: DefaultTaskAgent(agent_type, agent_id),
    )
    await manager.start_all(action_emitter=None)

    fact = FactRecord(
        agent_id="analytics:tenant-a",
        agent_type="analytics",
        agent_instance_id="tenant-a",
        event_type="ANALYTICS_EVENT",
        payload={"target_task_agent_type": "analytics", "target_task_agent_id": "tenant-a"},
    )
    await manager.add_fact_to_agent("analytics", "tenant-a", fact)
    await asyncio.sleep(0.1)

    assert manager.get_agent("analytics", "tenant-a") is not None
    await manager.stop_all()
