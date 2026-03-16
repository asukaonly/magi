from __future__ import annotations

from magi.agent.task_agents.chat_task_agent import ChatTaskAgent


def test_chat_task_agent_uses_injected_shared_skill_runner() -> None:
    shared_runner = object()

    agent = ChatTaskAgent(
        agent_id="chat-test",
        llm_adapter=None,
        skill_runner=shared_runner,
    )

    assert agent.function_calling_executor.skill_runner is shared_runner