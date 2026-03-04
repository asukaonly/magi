"""Tests for ChatTaskAgent modular prompt context integration."""

from __future__ import annotations

import unittest

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

        context = {
            "user_id": "u-chat",
            "session_id": "s-1",
            "user_message": "今天天气怎么样",
            "history": [{"role": "user", "content": "你好"}],
        }
        intent_result = {"intent": "chat"}
        tool_result = {"tools": ["weather"], "deep_thinking": False, "intent": "chat"}

        llm_params = await agent.assemble_llm_params(context, intent_result, tool_result)

        self.assertIn("prompt_context", llm_params)
        self.assertIn("system_prompt", llm_params)
        system_prompt = llm_params["system_prompt"]
        self.assertIn("# System Definition", system_prompt)
        self.assertIn("# Tool Information", system_prompt)
        self.assertIn("weather", system_prompt)


if __name__ == "__main__":
    unittest.main()
