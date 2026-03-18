from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from magi.context.retrieval import ContextRetrievalService


class _FakeL0Store:
    async def get_workbench(self, session_id: str):
        return {
            "session": session_id,
            "goal_stack": ["ship the fix"],
            "active_entities": ["repo:magi"],
            "temporary_tactics": ["stay small"],
        }


class _FakeUnifiedMemory:
    def __init__(self):
        self.l0 = _FakeL0Store()


class TestContextRetrievalService(unittest.IsolatedAsyncioTestCase):
    async def test_build_retrieved_memory_payload_loads_only_l0_without_hybrid_query(self) -> None:
        service = ContextRetrievalService(unified_memory=_FakeUnifiedMemory())

        with patch("magi.context.retrieval.HybridRetrievalService") as service_cls:
            payload = await service.build_retrieved_memory_payload(
                user_id="u1",
                session_id="s1",
                query="today",
                task_category="chat",
                allowed_layers=("L0",),
            )

            service_cls.assert_not_called()

        self.assertEqual(payload["l0_workbench"][0]["session"], "s1")
        self.assertEqual(payload["l2_entity_cards"], [])
        self.assertEqual(payload["l3_reflection_memory"], [])
        self.assertEqual(payload["l4_procedural_memory"], [])

    async def test_build_retrieved_memory_payload_queries_hybrid_retrieval(self) -> None:
        service = ContextRetrievalService(unified_memory=object())

        unified_payload = type(
            "Payload",
            (),
            {
                "l0_workbench": [{"summary": "Current goal"}],
                "l2_entity_cards": [{"entity_id": "user:u1"}],
                "l3_reflections": [{"summary": "User wants to switch jobs"}],
                "l4_procedures": [{"skill_name": "browser.open"}],
            },
        )()

        with patch("magi.context.retrieval.HybridRetrievalService") as service_cls:
            service_cls.return_value.query = AsyncMock(return_value=unified_payload)

            payload = await service.build_retrieved_memory_payload(
                user_id="u1",
                session_id="s1",
                query="switch jobs",
                task_category="chat",
                allowed_layers=("L0", "L4"),
            )

            # Should make exactly 1 query (no mode hint)
            service_cls.return_value.query.assert_called_once()

        self.assertEqual(payload["l0_workbench"][0]["summary"], "Current goal")
        self.assertEqual(payload["l2_entity_cards"], [])
        self.assertEqual(payload["l3_reflection_memory"], [])
        self.assertEqual(payload["l4_procedural_memory"][0]["skill_name"], "browser.open")
