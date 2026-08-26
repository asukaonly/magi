"""Tests for modular prompt context assembler and renderer."""

from __future__ import annotations

import unittest
from pathlib import Path

from magi.personality.models import EmotionalState, TaskBehaviorProfile
from magi.personality.loader import PersonalityConfig
from magi.context.assembler import PromptContextAssembler, PromptContextRenderer
from magi.context.user_profile_service import UserProfileService


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

    async def get_milestones(self, limit: int = 200):
        _ = limit
        return []


class _FakeL2EntityCatalog:
    async def list_entities(self, entity_ids=None, **kwargs):
        return [{"entity_id": "user:u1", "canonical_name": "Alice", "aliases": []}]


class _FakeL2Store:
    async def get_tom_snapshot(self, entity_id=None, entity_type=None):
        return {
            "preferences": {
                "language": "zh-CN",
                "style": "concise",
                "address.preferred": '["哈基米"]',
                "address.disallowed": '["老师"]',
                "address.real_name": "明日香",
            }
        }


class _FakeUnifiedMemory:
    def __init__(self):
        self.l2_entity_catalog = _FakeL2EntityCatalog()
        self.l2 = _FakeL2Store()


class TestPromptContextAssembler(unittest.IsolatedAsyncioTestCase):
    async def test_render_order_and_module_presence(self):
        assembler = PromptContextAssembler(
            user_profile_service=UserProfileService(unified_memory=_FakeUnifiedMemory()),
        )
        renderer = PromptContextRenderer()

        assembled = await assembler.assemble(
            agent_id="chat-agent",
            agent_type="chat",
            scenario="chat",
            task_category="chat",
            user_id="u1",
            self_memory=_FakeSelfMemory(),
            tool_result={"tools": ["weather"]},
            persona_name="test_persona",
            retrieved_memory_payload={
                "l0_workbench": [{"event": "recent_user_request"}],
                "l2_entity_cards": [{"entity_id": "user:u1"}],
                "l3_reflection_memory": [{"summary": "recent reflection"}],
                "l4_procedural_memory": [{"skill_name": "weather capability"}],
                "preference_memory": {},
            },
        )

        layers = renderer.render_prompt_layers(assembled)

        i_definition = layers.system_prompt.find("# System Definition")
        i_persona = layers.system_prompt.find("# Persona Runtime Plan")
        i_tools = layers.working_context.find("# Tool Use Guidance")
        i_profile = layers.working_context.find("# Profile Memory")

        self.assertTrue(i_definition >= 0)
        self.assertTrue(i_persona > i_definition)
        self.assertTrue(i_tools >= 0)
        self.assertTrue(i_profile > i_tools)
        self.assertIn("# Runtime World State", layers.runtime_world_state)
        self.assertNotIn("weather", layers.working_context)
        self.assertIn("* User Name: 哈基米", layers.working_context)
        self.assertIn("* Preferred Address: 哈基米", layers.working_context)
        self.assertIn("* Avoid Addressing As: 老师", layers.working_context)
        self.assertNotIn("### User Preferences", layers.working_context)
        self.assertNotIn("user_preferences", assembled.self_memory.retrieval_memory.preference_memory)

    async def test_profile_emotion_mapping_uses_relationship_scores(self):
        assembler = PromptContextAssembler(
            user_profile_service=UserProfileService(unified_memory=_FakeUnifiedMemory()),
        )

        assembled = await assembler.assemble(
            agent_id="chat-agent",
            agent_type="chat",
            scenario="chat",
            task_category="chat",
            user_id="u1",
            self_memory=_FakeSelfMemory(),
            tool_result={"tools": []},
            persona_name="test_persona",
            retrieved_memory_payload={},
        )

        emotion = assembled.profile_memory.recent_emotion
        self.assertEqual(emotion.get("emotion_label"), "positive")
        self.assertEqual(emotion.get("trust_label"), "high")


if __name__ == "__main__":
    unittest.main()


def test_chat_prompt_service_does_not_import_memory_retrieval_primitives() -> None:
    source = Path(__file__).resolve().parents[2] / "src/magi/chat/task_agent/prompt_service.py"
    text = source.read_text(encoding="utf-8")

    assert "get_unified_memory" not in text
    assert "HybridRetrievalService" not in text
    assert "build_query" not in text
