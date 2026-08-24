"""Tests for ChatTaskAgent modular prompt context integration."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from magi.agent.task_agents.handlers import (
    ChatRuntimeContext,
    GenericFactPayload,
    IncomingFactKind,
    IntentDecision,
    ToolSelection,
)
from magi.chat.task_agent.chat_task_agent import ChatTaskAgent
from magi.config.models import LLMScenario
from magi.llm.model_context import ModelContextProfile, ResolvedModel
from magi.personality.models import EmotionalState, TaskBehaviorProfile
from magi.personality.loader import PersonalityConfig


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


class _FakeL2EntityCatalog:
    async def list_entities(self, entity_ids=None, **kwargs):
        return [{"entity_id": "user:u-chat", "canonical_name": "Bob", "aliases": []}]


class _FakeL2Store:
    async def get_tom_snapshot(self, entity_id=None, entity_type=None):
        return {"preferences": {"locale": "zh-CN"}}


class _FakeUnifiedMemory:
    def __init__(self):
        self.l2_entity_catalog = _FakeL2EntityCatalog()
        self.l2 = _FakeL2Store()
        self.l0 = None


class _RecordingLLMPool:
    def __init__(self, adapter):
        self._adapter = adapter
        self.requested: list[LLMScenario] = []

    def get(self, scenario: LLMScenario):
        self.requested.append(scenario)
        return self._adapter

    def resolve(self, scenario: LLMScenario) -> ResolvedModel:
        return ResolvedModel(
            adapter=self.get(scenario),
            context=ModelContextProfile(
                provider_id="openai",
                model_id="fake-model",
                context_window=128_000,
                max_output_tokens=8_192,
            ),
        )


class _FakeHybridRetrievalService:
    def __init__(self) -> None:
        self.query = AsyncMock(
            return_value=type(
                "Payload",
                (),
                {
                    "l0_workbench": [],
                    "l2_entity_cards": [],
                    "l3_reflections": [],
                    "l4_procedures": [],
                },
            )()
        )


class TestChatTaskAgentPromptModules(unittest.IsolatedAsyncioTestCase):
    async def test_assemble_llm_params_contains_modular_prompt(self):
        agent = ChatTaskAgent(
            agent_id="u-chat",
            llm_adapter=_FakeLLMAdapter(),
            memory=_FakeSelfMemory(),
            unified_memory=_FakeUnifiedMemory(),
            hybrid_retrieval_service=_FakeHybridRetrievalService(),
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
            latest_user_message="今天天气怎么样",
            incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
            latest_payload=GenericFactPayload(),
        )
        intent_result = IntentDecision(
            intent="unified_agent_run",
            execution_mode=None,
            tools=["weather"],
        )
        tool_result = ToolSelection(tools=["weather"], reasoning="weather lookup")

        llm_params = await agent.assemble_llm_params(context, intent_result, tool_result)

        self.assertIsNotNone(llm_params.prompt_context)
        system_prompt = llm_params.system_prompt
        self.assertIn("# System Definition", system_prompt)
        self.assertIn("# Tool Use Guidance", system_prompt)
        self.assertNotIn("weather", system_prompt)
        self.assertIsNone(llm_params.mode)

    async def test_chat_task_agent_uses_core_scenario_from_pool(self):
        pool = _RecordingLLMPool(_FakeLLMAdapter())
        agent = ChatTaskAgent(
            agent_id="u-chat",
            llm_pool=pool,
            memory=_FakeSelfMemory(),
            unified_memory=_FakeUnifiedMemory(),
            hybrid_retrieval_service=_FakeHybridRetrievalService(),
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
            latest_user_message="帮我查下天气",
            incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
            latest_payload=GenericFactPayload(),
        )
        intent_result = IntentDecision(
            intent="unified_agent_run",
            execution_mode=None,
            tools=[],
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
