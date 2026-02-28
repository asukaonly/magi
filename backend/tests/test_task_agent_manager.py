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

from magi.core.runtime import TaskAgent, TaskAgentManager, TaskAgentType
from magi.agent.task_agents import DefaultTaskAgent
from magi.core.runtime.contracts import FactRecord


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
        create_memory_digest_agent=lambda agent_id: _CollectTaskAgent(TaskAgentType.MEMORY_DIGEST, agent_id),
        create_daily_report_agent=lambda agent_id: _CollectTaskAgent(TaskAgentType.DAILY_REPORT, agent_id),
    )
    await manager.start_all(action_executor=None)

    # Core instances should exist.
    assert manager.get_agent(TaskAgentType.CHAT, "default") is not None
    assert manager.get_agent(TaskAgentType.MEMORY_DIGEST, "default") is not None

    # Dynamic instance should be created on demand.
    fact = FactRecord(
        agent_id="daily_report:20260228",
        agent_type=TaskAgentType.DAILY_REPORT.value,
        agent_instance_id="20260228",
        event_type="CRON_EVENT",
        payload={"job": "daily_report"},
    )
    await manager.add_fact_to_agent(TaskAgentType.DAILY_REPORT, "20260228", fact)
    await asyncio.sleep(0.2)

    dynamic = manager.get_agent(TaskAgentType.DAILY_REPORT, "20260228")
    assert dynamic is not None
    assert dynamic.get_stats()["processed"] >= 1

    await manager.stop_all()


@pytest.mark.asyncio
async def test_task_agent_manager_supports_default_agent_type():
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: _CollectTaskAgent(TaskAgentType.CHAT, agent_id),
        create_memory_digest_agent=lambda agent_id: _CollectTaskAgent(TaskAgentType.MEMORY_DIGEST, agent_id),
        create_daily_report_agent=lambda agent_id: _CollectTaskAgent(TaskAgentType.DAILY_REPORT, agent_id),
        create_default_agent=lambda agent_type, agent_id: DefaultTaskAgent(agent_type, agent_id),
    )
    await manager.start_all(action_executor=None)

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
