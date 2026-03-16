from __future__ import annotations

from magi.agent.task_agents.chat_task_agent import ChatTaskAgent


def test_chat_task_agent_uses_injected_shared_skill_executor() -> None:
    shared_executor = object()

    agent = ChatTaskAgent(
        agent_id="chat-test",
        llm_adapter=None,
        skill_executor=shared_executor,
    )

    assert agent.function_calling_executor.skill_executor is shared_executor