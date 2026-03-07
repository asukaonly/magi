"""Tests for ChatTaskAgent modular prompt context integration."""

from __future__ import annotations

import unittest

from magi.agent.task_agents.chat import (
    ChatRuntimeContext,
    ExecutionMode,
    IncomingFactKind,
    IntentDecision,
    OrchestrationPlan,
    ToolSelection,
)
from magi.agent.task_agents.chat_task_agent import ChatTaskAgent
from magi.memory.models import EmotionalState, TaskBehaviorProfile
from magi.memory.personality_loader import PersonalityConfig


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False


class _FakeSelfMemory:
    personality_name = "default"

    async def get_core_personality(self):
        return PersonalityConfig()

    async def get_emotional_state(self):
        return EmotionalState(current_mood="neutral")

    async def get_behavior_profile(self, task_category: str):
        return TaskBehaviorProfile(task_category=task_category)

    async def get_relationship(self, user_id: str):
        _ = user_id
        return {"sentiment_score": -0.1, "trust_level": 0.5}


class _FakeProfile:
    def __init__(self):
        self.name = "Bob"
        self.preferences = {"locale": "zh-CN"}


class _FakeOtherMemory:
    def get_profile(self, user_id: str):
        _ = user_id
        return _FakeProfile()


class TestChatTaskAgentPromptModules(unittest.IsolatedAsyncioTestCase):
    async def test_assemble_llm_params_contains_modular_prompt(self):
        agent = ChatTaskAgent(
            agent_id="u-chat",
            llm_adapter=_FakeLLMAdapter(),
            memory=_FakeSelfMemory(),
            other_memory=_FakeOtherMemory(),
        )

        context = ChatRuntimeContext(
            latest_fact=None,
            recent_facts=[],
            batch_facts=[],
            agent_id="u-chat",
            agent_type="chat",
            runtime_key="chat:u-chat",
            user_id="u-chat",
            session_id="s-1",
            history_key="u-chat::s-1",
            history=[{"role": "user", "content": "你好"}],
            conversation_history=[{"role": "user", "content": "你好"}],
            active_orchestrations=[],
            latest_user_message="今天天气怎么样",
            incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
            latest_payload={},
        )
        intent_result = IntentDecision(
            intent="chat",
            difficulty="normal",
            execution_mode=ExecutionMode.FUNCTION_CALLING,
            tools=["weather"],
            deep_thinking=False,
            orchestration_plan=OrchestrationPlan(),
        )
        tool_result = ToolSelection(tools=["weather"], reasoning="weather lookup")

        llm_params = await agent.assemble_llm_params(context, intent_result, tool_result)

        self.assertIn("prompt_context", llm_params.prompt_payload)
        self.assertIn("system_prompt", llm_params.prompt_payload)
        system_prompt = llm_params.prompt_payload["system_prompt"]
        self.assertIn("# System Definition", system_prompt)
        self.assertIn("# Tool Information", system_prompt)
        self.assertIn("weather", system_prompt)
        self.assertEqual(llm_params.mode, ExecutionMode.FUNCTION_CALLING)


if __name__ == "__main__":
    unittest.main()
