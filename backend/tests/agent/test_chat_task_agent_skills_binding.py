from __future__ import annotations

from magi.chat.task_agent.chat_task_agent import ChatTaskAgent


def test_chat_task_agent_uses_injected_shared_skill_runner() -> None:
    shared_runner = object()

    agent = ChatTaskAgent(
        agent_id="chat-test",
        llm_adapter=None,
        skill_runner=shared_runner,
    )

    assert agent.function_calling_orchestrator.skill_runner is shared_runner