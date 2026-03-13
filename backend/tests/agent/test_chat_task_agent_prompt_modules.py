"""Tests for ChatTaskAgent modular prompt context integration."""

from __future__ import annotations

import unittest

from magi.agent.task_agents.chat import (
    ChatRuntimeContext,
    ExecutionMode,
    GenericFactPayload,
    IncomingFactKind,
    IntentDecision,
    OrchestrationPlan,
    ToolSelection,
)
from magi.agent.task_agents.chat_task_agent import ChatTaskAgent
from magi.config.models import LLMScenario
from magi.memory.models import EmotionalState, TaskBehaviorProfile
from magi.memory.personality_loader import PersonalityConfig


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False
    provider_name = "openai"

    async def chat(self, **kwargs):
        _ = kwargs
        return "ok"


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


class _RecordingLLMPool:
    def __init__(self, adapter):
        self._adapter = adapter
        self.requested: list[LLMScenario] = []

    def get(self, scenario: LLMScenario):
        self.requested.append(scenario)
        return self._adapter


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
            latest_payload=GenericFactPayload(),
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

        self.assertIsNotNone(llm_params.prompt_context)
        system_prompt = llm_params.system_prompt
        self.assertIn("# System Definition", system_prompt)
        self.assertIn("# Tool Information", system_prompt)
        self.assertIn("weather", system_prompt)
        self.assertEqual(llm_params.mode, ExecutionMode.FUNCTION_CALLING)

    async def test_chat_task_agent_uses_core_scenario_from_pool(self):
        pool = _RecordingLLMPool(_FakeLLMAdapter())
        agent = ChatTaskAgent(
            agent_id="u-chat",
            llm_pool=pool,
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
            latest_user_message="帮我查下天气",
            incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
            latest_payload=GenericFactPayload(),
        )
        intent_result = IntentDecision(
            intent="chat",
            difficulty="normal",
            execution_mode=ExecutionMode.DIRECT_LLM,
            tools=[],
            deep_thinking=False,
            orchestration_plan=OrchestrationPlan(),
        )
        tool_result = ToolSelection(tools=[], reasoning="direct reply")

        await agent.assemble_llm_params(context, intent_result, tool_result)
        await agent._prompt_service.call_llm(
            system_prompt="You are helpful.",
            messages=[{"role": "user", "content": "你好"}],
        )

        self.assertIn(LLMScenario.CORE, pool.requested)


if __name__ == "__main__":
    unittest.main()
