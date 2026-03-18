from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from magi.context import ContextAssemblyService, PromptContextAssembler, PromptContextRenderer
from magi.personality.loader import PersonalityConfig
from magi.personality.models import EmotionalState


class _FakeMemory:
    personality_name = "default"

    async def get_core_personality(self):
        return PersonalityConfig()

    async def get_emotional_state(self):
        return EmotionalState(current_mood="focused", mood_intensity=0.8, energy_level=0.7, stress_level=0.2)

    async def get_relationship(self, user_id: str):
        _ = user_id
        return {"sentiment_score": 0.2, "trust_level": 0.6}


class TestContextAssemblyService(unittest.IsolatedAsyncioTestCase):
    async def test_build_prompt_package_uses_user_message_for_retrieval_query(self):
        retrieval_memory_provider = AsyncMock(
            return_value={
                "l0_workbench": [{"summary": "Current goal"}],
                "l2_entity_cards": [{"entity_id": "user:u1"}],
                "l3_reflection_memory": [{"summary": "User wants to switch jobs"}],
                "l4_procedural_memory": [{"skill_name": "browser.open"}],
                "preference_memory": {},
            }
        )
        service = ContextAssemblyService(
            agent_id="chat-agent",
            agent_type="chat",
            prompt_context_assembler=PromptContextAssembler(),
            prompt_context_renderer=PromptContextRenderer(),
            memory=_FakeMemory(),
            other_memory=None,
            retrieval_memory_provider=retrieval_memory_provider,
        )

        package = await service.build_prompt_package(
            user_id="u1",
            session_id="s1",
            user_message="帮我回忆昨天聊过的重构方案",
            task_category="chat",
            tools=[],
            recent_tool_errors=[
                {
                    "tool_name": "memory_query",
                    "error_code": "TIMEOUT",
                    "error_message": "request timed out",
                }
            ],
        )

        retrieval_memory_provider.assert_awaited_once_with(
            user_id="u1",
            session_id="s1",
            query="帮我回忆昨天聊过的重构方案",
            task_category="chat",
        )
        self.assertIn("# Recent Tool Errors", package.system_prompt)
        self.assertEqual(package.prompt_context.self_memory.retrieval_memory.l0_workbench[0]["summary"], "Current goal")
