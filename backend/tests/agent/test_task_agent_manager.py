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
    await manager.start_all(event_emitter=None)

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
    await manager.start_all(event_emitter=None)

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


def _user_fact(session_id: str) -> FactRecord:
    return FactRecord(
        agent_id=f"chat:{session_id}",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id=session_id,
        event_type="USER_MESSAGE",
        payload={"content": "hi"},
    )


@pytest.mark.asyncio
async def test_evicts_oldest_idle_instance_instead_of_silently_rejecting():
    """At capacity with an idle instance available, a new session must reclaim
    the oldest idle slot rather than being silently dropped (regression for the
    no-op _maybe_evict_idle_instances bug)."""
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _CollectTaskAgent(TaskAgentType.CHAT, agent_id),
        max_dynamic_instances=2,
    )
    await manager.start_all(event_emitter=None)

    # Two idle dynamic instances fill capacity (empty fact queues).
    await manager.ensure_agent(TaskAgentType.CHAT, "s-old")
    await asyncio.sleep(0.01)  # make s-old strictly older than s-new
    await manager.ensure_agent(TaskAgentType.CHAT, "s-new")

    # Third session arrives at capacity. The oldest idle instance must be
    # recycled so the new session is accepted — not silently dropped.
    accepted = await manager.add_fact_to_agent(
        TaskAgentType.CHAT, "s-third", _user_fact("s-third")
    )

    assert accepted is True
    assert manager.get_agent(TaskAgentType.CHAT, "s-third") is not None
    assert manager.get_agent(TaskAgentType.CHAT, "s-old") is None
    assert manager.get_agent(TaskAgentType.CHAT, "s-new") is not None

    await manager.stop_all()


class _NeverConsumeTaskAgent(TaskAgent):
    """TaskAgent that never drains its queue — simulates a permanently busy instance."""

    async def start(self, *args, **kwargs) -> None:
        pass  # intentionally do not spawn the consume loop

    async def stop(self) -> None:
        pass


@pytest.mark.asyncio
async def test_does_not_evict_busy_instance_and_rejects_explicitly_when_full():
    """At capacity with no idle instance to reclaim, a new session is rejected
    explicitly (observable via return value + counter) and the busy instance is
    not evicted."""
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _NeverConsumeTaskAgent(
            agent_type=TaskAgentType.CHAT, agent_id=agent_id
        ),
        max_dynamic_instances=1,
    )
    await manager.start_all(event_emitter=None)

    # Occupy the only dynamic slot with a BUSY instance (non-empty queue).
    busy = await manager.ensure_agent(TaskAgentType.CHAT, "busy")
    busy._fact_queue.put_nowait(_user_fact("busy"))
    assert busy._fact_queue.qsize() == 1

    # New session at capacity with nothing idle to reclaim: must be rejected
    # explicitly, and the busy instance must survive.
    accepted = await manager.add_fact_to_agent(
        TaskAgentType.CHAT, "overflow", _user_fact("overflow")
    )

    assert accepted is False
    assert manager.get_agent(TaskAgentType.CHAT, "overflow") is None
    assert manager.get_agent(TaskAgentType.CHAT, "busy") is not None
    assert manager.get_stats()["enqueue_rejected_count"] >= 1

    await manager.stop_all()
