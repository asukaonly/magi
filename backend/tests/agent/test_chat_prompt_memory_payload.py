from __future__ import annotations

import unittest

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
        return {"preferences": {"language": "zh-CN", "style": "concise"}}


class _FakeUnifiedMemory:
    def __init__(self):
        self.l2_entity_catalog = _FakeL2EntityCatalog()
        self.l2 = _FakeL2Store()


class TestChatPromptMemoryPayload(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_context_reads_l0_l2_l3_l4_payloads(self):
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
                "l0_workbench": [
                    {
                        "session": {"session_id": "s1"},
                        "attention_items": [
                            {
                                "kind": "situation",
                                "summary": "The user needs a gentle response.",
                                "status": "active",
                                "evidence_mode": "direct",
                            }
                        ],
                    }
                ],
                "l2_entity_cards": [{"entity_id": "user:u1", "stress_level": "high"}],
                "l3_reflection_memory": [{"summary": "User wants to switch jobs"}],
                "l4_procedural_memory": [{"skill_name": "browser.open", "success_rate": 0.8}],
                "preference_memory": {},
            },
        )

        prompt = renderer.render_system_prompt(assembled)

        self.assertEqual(
            assembled.self_memory.retrieval_memory.l0_workbench[0][
                "attention_items"
            ][0]["kind"],
            "situation",
        )
        self.assertEqual(assembled.self_memory.retrieval_memory.l2_entity_cards[0]["entity_id"], "user:u1")
        self.assertEqual(assembled.self_memory.retrieval_memory.l3_reflection_memory[0]["summary"], "User wants to switch jobs")
        self.assertEqual(assembled.self_memory.retrieval_memory.l4_procedural_memory[0]["skill_name"], "browser.open")
        self.assertIn("Procedural Memory (L4)", prompt)
        self.assertIn("Entity Cards (L2)", prompt)
        self.assertIn("Current situation: The user needs a gentle response.", prompt)
