import pytest

from magi.agent.task_agents.default_task_agent import DefaultTaskAgent
from magi.agent.task_agents.timeline_task_agent import TimelineTaskAgent
from magi.agent.runtime.contracts import FactRecord
from magi.agent.runtime.task_agent_manager import TaskAgentManager
from magi.agent.runtime.types import TaskAgentType


async def _noop_timeline_handler(payload):
    return payload


@pytest.mark.asyncio
async def test_timeline_task_agent_processes_timeline_facts():
    agent = TimelineTaskAgent(agent_id="timeline-main", timeline_handler=_noop_timeline_handler)

    await agent.start(action_emitter=None)
    accepted = await agent.add_fact(
        FactRecord(
            agent_id="timeline:timeline-main",
            agent_type=TaskAgentType.TIMELINE.value,
            agent_instance_id="timeline-main",
            event_type="TimelineSourceDetected",
            payload={"source_type": "manual_journal", "source_item_id": "evt-1"},
        )
    )

    assert accepted is True

    for _ in range(20):
        if agent.get_stats()["processed"] >= 1:
            break
        import asyncio

        await asyncio.sleep(0.05)

    await agent.stop()

    stats = agent.get_stats()
    assert stats["processed"] >= 1


@pytest.mark.asyncio
async def test_task_agent_manager_creates_timeline_agents():
    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: DefaultTaskAgent(TaskAgentType.CHAT, agent_id),
        create_default_agent=lambda agent_type, agent_id: (
            TimelineTaskAgent(agent_id=agent_id, timeline_handler=_noop_timeline_handler)
            if agent_type == TaskAgentType.TIMELINE.value
            else DefaultTaskAgent(agent_type, agent_id)
        ),
    )

    await manager.start_all(action_emitter=None)
    agent = await manager.ensure_agent(TaskAgentType.TIMELINE, "timeline-main")
    await manager.stop_all()

    assert agent.agent_type == TaskAgentType.TIMELINE
