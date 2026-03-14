from __future__ import annotations

import unittest

from magi.memory.models import EmotionalState, TaskBehaviorProfile
from magi.memory.personality_loader import PersonalityConfig
from magi.memory.prompt_context_assembler import PromptContextAssembler, PromptContextRenderer


class _FakeSelfMemory:
    async def get_core_personality(self):
        return PersonalityConfig()

    async def get_emotional_state(self):
        return EmotionalState(current_mood="focused", mood_intensity=0.8, energy_level=0.75, stress_level=0.2)

    async def get_behavior_profile(self, task_category: str):
        return TaskBehaviorProfile(task_category=task_category)

    async def get_relationship(self, user_id: str):
        _ = user_id
        return {"sentiment_score": 0.6, "trust_level": 0.8}


class _FakeProfile:
    def __init__(self):
        self.name = "Alice"
        self.preferences = {"language": "zh-CN", "style": "concise"}


class _FakeOtherMemory:
    def get_profile(self, user_id: str):
        _ = user_id
        return _FakeProfile()


class _FakeToolRegistry:
    def get_all_tools_info(self):
        return [
            {"name": "weather", "description": "Get weather details", "category": "builtin", "type": "tool"},
        ]


class TestChatPromptMemoryPayload(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_context_reads_l0_l2_l3_l4_payloads(self):
        assembler = PromptContextAssembler(tool_registry=_FakeToolRegistry())
        renderer = PromptContextRenderer()

        assembled = await assembler.assemble(
            agent_id="chat-agent",
            agent_type="chat",
            scenario="chat",
            task_category="chat",
            user_id="u1",
            self_memory=_FakeSelfMemory(),
            other_memory=_FakeOtherMemory(),
            tool_result={"tools": ["weather"]},
            retrieved_memory_payload={
                "l0_workbench": [{"summary": "Current goal: comfort the user"}],
                "l2_entity_cards": [{"entity_id": "user:u1", "stress_level": "high"}],
                "l3_reflection_memory": [{"summary": "User wants to switch jobs"}],
                "l4_procedural_memory": [{"skill_name": "browser.open", "success_rate": 0.8}],
                "preference_memory": {"task_preferences": {"verbosity": "low"}},
            },
        )

        prompt = renderer.render_system_prompt(assembled)

        self.assertEqual(assembled.self_memory.retrieval_memory.l0_workbench[0]["summary"], "Current goal: comfort the user")
        self.assertEqual(assembled.self_memory.retrieval_memory.l2_entity_cards[0]["entity_id"], "user:u1")
        self.assertEqual(assembled.self_memory.retrieval_memory.l3_reflection_memory[0]["summary"], "User wants to switch jobs")
        self.assertEqual(assembled.self_memory.retrieval_memory.l4_procedural_memory[0]["skill_name"], "browser.open")
        self.assertIn("Procedural Memory (L4)", prompt)
        self.assertIn("Entity Cards (L2)", prompt)
