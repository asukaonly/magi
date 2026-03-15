"""Tests for modular prompt context assembler and renderer."""

from __future__ import annotations

import unittest

from magi.personality.models import EmotionalState, TaskBehaviorProfile
from magi.personality.loader import PersonalityConfig
from magi.context.assembler import PromptContextAssembler, PromptContextRenderer


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
            {"name": "web_search", "description": "Search web", "category": "builtin", "type": "tool"},
        ]


class TestPromptContextAssembler(unittest.IsolatedAsyncioTestCase):
    async def test_render_order_and_module_presence(self):
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
                "l0_workbench": [{"event": "recent_user_request"}],
                "l2_entity_cards": [{"entity_id": "user:u1"}],
                "l3_reflection_memory": [{"summary": "recent reflection"}],
                "l4_procedural_memory": [{"skill_name": "weather capability"}],
                "preference_memory": {"task_preferences": {"verbosity": "low"}},
            },
        )

        prompt = renderer.render_system_prompt(assembled)

        i1 = prompt.find("# System Definition")
        i2 = prompt.find("# Persona Entity")
        i3 = prompt.find("# Profile Memory")
        i4 = prompt.find("# System Information")
        i5 = prompt.find("# Tool Information")

        self.assertTrue(i1 >= 0)
        self.assertTrue(i2 > i1)
        self.assertTrue(i3 > i1)
        self.assertTrue(i4 > i3)
        self.assertTrue(i5 > i4)
        self.assertIn("weather", prompt)

    async def test_profile_emotion_mapping_uses_relationship_scores(self):
        assembler = PromptContextAssembler(tool_registry=_FakeToolRegistry())

        assembled = await assembler.assemble(
            agent_id="chat-agent",
            agent_type="chat",
            scenario="chat",
            task_category="chat",
            user_id="u1",
            self_memory=_FakeSelfMemory(),
            other_memory=_FakeOtherMemory(),
            tool_result={"tools": []},
            retrieved_memory_payload={},
        )

        emotion = assembled.profile_memory.recent_emotion
        self.assertEqual(emotion.get("emotion_label"), "positive")
        self.assertEqual(emotion.get("trust_label"), "high")


if __name__ == "__main__":
    unittest.main()
