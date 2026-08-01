from __future__ import annotations

import asyncio

import pytest

from magi.agent.runtime.contracts import FactRecord
from magi.agent.runtime.task_agent import TaskAgent
from magi.agent.runtime.task_agent_manager import TaskAgentManager
from magi.agent.runtime.types import TaskAgentType
from magi.agent.task_agents.common import ExploreTaskCompletedPayload
from magi.agent.task_agents.explore.constants import EXPLORE_TASK_COMPLETED
from magi.agent.task_agents.explore.postprocess_service import ExplorePostProcessService
from magi.agent.workers.worker_state import WORKER_AGENT_COMPLETED


class _IdleTaskAgent(TaskAgent):
    async def handle_fact(self, fact: FactRecord) -> None:
        _ = fact


def _build_manager(*, generation_getter=None) -> TaskAgentManager:
    return TaskAgentManager(
        create_chat_agent=lambda agent_id: _IdleTaskAgent(
            TaskAgentType.CHAT,
            agent_id,
        ),
        create_default_agent=lambda agent_type, agent_id: _IdleTaskAgent(
            agent_type,
            agent_id,
        ),
        user_message_generation_getter=generation_getter,
    )


@pytest.mark.asyncio
async def test_global_clear_removes_chat_and_explore_agents() -> None:
    manager = _build_manager()
    await manager.start_all(event_emitter=None)
    await manager.ensure_agent(TaskAgentType.EXPLORE, "user-1")

    try:
        cancelled_count = await manager.pause_chat_work_and_cancel_all()

        assert cancelled_count == 2
        assert manager.get_agent(TaskAgentType.CHAT, "default") is None
        assert manager.get_agent(TaskAgentType.EXPLORE, "user-1") is None
    finally:
        await manager.resume_chat_work()
        await manager.stop_all()


@pytest.mark.asyncio
async def test_explore_completion_without_generation_fails_closed() -> None:
    manager = _build_manager(generation_getter=lambda: 1)
    service = ExplorePostProcessService(get_task_agent_manager=lambda: manager)
    await manager.start_all(event_emitter=None)

    try:
        emitted = await service._emit_upstream_fact(
            event_type=EXPLORE_TASK_COMPLETED,
            upstream_task_agent_type=TaskAgentType.CHAT.value,
            upstream_task_agent_id="session-1",
            payload=ExploreTaskCompletedPayload(
                user_id="user-1",
                session_id="session-1",
                root_user_message="old request",
                markdown_dossier="old report",
            ),
            correlation_id="corr-old",
            user_message_generation=None,
        )

        assert emitted is False
        assert manager.get_agent(TaskAgentType.CHAT, "session-1") is None
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_stale_explore_completion_waiting_at_clear_is_rejected() -> None:
    generation = 0
    manager = _build_manager(generation_getter=lambda: generation)
    await manager.start_all(event_emitter=None)
    await manager.pause_chat_work_and_cancel_all()

    stale_completion = FactRecord(
        agent_id="chat:session-1",
        agent_type=TaskAgentType.CHAT.value,
        agent_instance_id="session-1",
        event_type=EXPLORE_TASK_COMPLETED,
        payload={
            "user_id": "user-1",
            "session_id": "session-1",
            "markdown_dossier": "old report",
        },
        user_message_generation=0,
    )
    delivery = asyncio.create_task(
        manager.add_fact_to_agent(
            TaskAgentType.CHAT,
            "session-1",
            stale_completion,
        )
    )

    try:
        await asyncio.sleep(0)
        assert not delivery.done()

        generation = 1
        await manager.resume_chat_work()

        assert await asyncio.wait_for(delivery, timeout=1) is False
        assert manager.get_agent(TaskAgentType.CHAT, "session-1") is None
    finally:
        if not delivery.done():
            delivery.cancel()
            await asyncio.gather(delivery, return_exceptions=True)
        await manager.resume_chat_work()
        await manager.stop_all()


@pytest.mark.asyncio
async def test_stale_worker_update_cannot_recreate_explore_after_clear() -> None:
    generation = 0
    manager = _build_manager(generation_getter=lambda: generation)
    await manager.start_all(event_emitter=None)
    await manager.pause_chat_work_and_cancel_all()

    stale_worker_update = FactRecord(
        agent_id="explore:user-1",
        agent_type=TaskAgentType.EXPLORE.value,
        agent_instance_id="user-1",
        event_type=WORKER_AGENT_COMPLETED,
        payload={
            "user_id": "user-1",
            "session_id": "session-1",
            "worker_id": "worker-old",
        },
        user_message_generation=0,
    )
    delivery = asyncio.create_task(
        manager.add_fact_to_agent(
            TaskAgentType.EXPLORE,
            "user-1",
            stale_worker_update,
        )
    )

    try:
        await asyncio.sleep(0)
        assert not delivery.done()

        generation = 1
        await manager.resume_chat_work()

        assert await asyncio.wait_for(delivery, timeout=1) is False
        assert manager.get_agent(TaskAgentType.EXPLORE, "user-1") is None
    finally:
        if not delivery.done():
            delivery.cancel()
            await asyncio.gather(delivery, return_exceptions=True)
        await manager.resume_chat_work()
        await manager.stop_all()
