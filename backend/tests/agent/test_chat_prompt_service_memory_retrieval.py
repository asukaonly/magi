from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from magi.agent.task_agents.chat.prompt_service import ChatPromptService
from magi.personality.models import EmotionalState
from magi.personality.loader import PersonalityConfig
from magi.context.assembler import PromptContextAssembler, PromptContextRenderer


class _FakeMemory:
    personality_name = "default"

    async def get_core_personality(self):
        return PersonalityConfig()

    async def get_emotional_state(self):
        return EmotionalState(current_mood="focused", mood_intensity=0.8, energy_level=0.7, stress_level=0.2)

    async def get_relationship(self, user_id: str):
        _ = user_id
        return {"sentiment_score": 0.2, "trust_level": 0.6}


class TestChatPromptServiceMemoryRetrieval(unittest.IsolatedAsyncioTestCase):
    async def test_build_prompt_context_includes_hybrid_memory_payload(self):
        service = ChatPromptService(
            agent_id="chat-agent",
            agent_type="chat",
            prompt_context_assembler=PromptContextAssembler(),
            prompt_context_renderer=PromptContextRenderer(),
            memory=_FakeMemory(),
            other_memory=None,
        )

        detail_payload = type(
            "Payload",
            (),
            {
                "l0_workbench": [{"summary": "Current goal"}],
                "l2_entity_cards": [{"entity_id": "user:u1"}],
                "l3_reflections": [],
                "l4_procedures": [],
                "trace": {"query_mode": "detail"},
            },
        )()
        summary_payload = type(
            "Payload",
            (),
            {
                "l0_workbench": [],
                "l2_entity_cards": [],
                "l3_reflections": [{"summary": "User wants to switch jobs"}],
                "l4_procedures": [],
                "trace": {"query_mode": "summary"},
            },
        )()
        experience_payload = type(
            "Payload",
            (),
            {
                "l0_workbench": [],
                "l2_entity_cards": [],
                "l3_reflections": [],
                "l4_procedures": [{"skill_name": "browser.open"}],
                "trace": {"query_mode": "experience"},
            },
        )()

        with patch("magi.agent.task_agents.chat.prompt_service.get_unified_memory", return_value=object()):
            with patch("magi.agent.task_agents.chat.prompt_service.HybridRetrievalService") as service_cls:
                service_cls.return_value.query = AsyncMock(
                    side_effect=[detail_payload, summary_payload, experience_payload]
                )

                context = await service.build_prompt_context(
                    user_id="u1",
                    session_id="s1",
                    task_category="chat",
                    tools=[],
                )

        retrieval = context.self_memory.retrieval_memory
        self.assertEqual(retrieval.l0_workbench[0]["summary"], "Current goal")
        self.assertEqual(retrieval.l2_entity_cards[0]["entity_id"], "user:u1")
        self.assertEqual(retrieval.l3_reflection_memory[0]["summary"], "User wants to switch jobs")
        self.assertEqual(retrieval.l4_procedural_memory[0]["skill_name"], "browser.open")
