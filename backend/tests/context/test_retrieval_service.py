from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

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
        retrieval_service = MagicMock()
        service = ContextRetrievalService(
            unified_memory=_FakeUnifiedMemory(),
            retrieval_service=retrieval_service,
        )

        payload = await service.build_retrieved_memory_payload(
            user_id="u1",
            session_id="s1",
            query="today",
            task_category="chat",
            allowed_layers=("L0",),
        )

        self.assertEqual(payload["l0_workbench"][0]["session"], "s1")
        self.assertEqual(payload["l2_entity_cards"], [])
        self.assertEqual(payload["l3_reflection_memory"], [])
        self.assertEqual(payload["l4_procedural_memory"], [])
        retrieval_service.query.assert_not_called()

    async def test_build_retrieved_memory_payload_queries_hybrid_retrieval(self) -> None:
        retrieval_service = MagicMock()
        service = ContextRetrievalService(
            unified_memory=object(),
            retrieval_service=retrieval_service,
        )

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

        retrieval_service.query = AsyncMock(return_value=unified_payload)
        payload = await service.build_retrieved_memory_payload(
            user_id="u1",
            session_id="s1",
            query="switch jobs",
            task_category="chat",
            allowed_layers=("L0", "L4"),
        )

        retrieval_service.query.assert_called_once()

        self.assertEqual(payload["l0_workbench"][0]["summary"], "Current goal")
        self.assertEqual(payload["l2_entity_cards"], [])
        self.assertEqual(payload["l3_reflection_memory"], [])
        self.assertEqual(payload["l4_procedural_memory"][0]["skill_name"], "browser.open")

    async def test_build_retrieved_memory_payload_requires_injected_service_for_hybrid_queries(self) -> None:
        service = ContextRetrievalService(unified_memory=object(), retrieval_service=None)

        with self.assertRaises(RuntimeError):
            await service.build_retrieved_memory_payload(
                user_id="u1",
                session_id="s1",
                query="switch jobs",
                task_category="chat",
                allowed_layers=("L0", "L3"),
            )
