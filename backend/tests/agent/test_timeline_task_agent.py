import pytest

from magi.agent.task_agents.default_task_agent import DefaultTaskAgent
from magi.agent.task_agents.timeline_task_agent import TimelineTaskAgent
from magi.agent.runtime.contracts import FactRecord
from magi.agent.runtime.task_agent_manager import TaskAgentManager
from magi.agent.runtime.types import TaskAgentType


@pytest.mark.asyncio
async def test_manager_created_timeline_agent_delivers_exact_source_fact():
    import asyncio

    entered = asyncio.Event()
    received = []

    async def handler(payload):
        received.append(payload)
        entered.set()

    manager = TaskAgentManager(
        create_chat_agent=lambda agent_id: DefaultTaskAgent(TaskAgentType.CHAT, agent_id),
        create_default_agent=lambda agent_type, agent_id: (
            TimelineTaskAgent(agent_id=agent_id, timeline_handler=handler)
            if agent_type == TaskAgentType.TIMELINE.value
            else DefaultTaskAgent(agent_type, agent_id)
        ),
    )
    await manager.start_all(event_emitter=None)
    try:
        agent = await manager.ensure_agent(TaskAgentType.TIMELINE, "timeline-main")
        assert agent.agent_type == TaskAgentType.TIMELINE
        payload = {"source_type": "photo_library", "source_item_id": "evt-1"}
        assert (
            await agent.add_fact(
                FactRecord(
                    agent_id="timeline:timeline-main",
                    agent_type=TaskAgentType.TIMELINE.value,
                    agent_instance_id="timeline-main",
                    event_type="TimelineSourceDetected",
                    payload=payload,
                )
            )
            is True
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert received == [payload]
    finally:
        await manager.stop_all()
