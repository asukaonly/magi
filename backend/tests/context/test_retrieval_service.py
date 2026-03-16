from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from magi.context.retrieval import ContextRetrievalService


class TestContextRetrievalService(unittest.IsolatedAsyncioTestCase):
    async def test_build_retrieved_memory_payload_queries_hybrid_retrieval(self) -> None:
        service = ContextRetrievalService()

        detail_payload = type(
            "Payload",
            (),
            {
                "l0_workbench": [{"summary": "Current goal"}],
                "l2_entity_cards": [{"entity_id": "user:u1"}],
                "l3_reflections": [],
                "l4_procedures": [],
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
            },
        )()

        with patch("magi.context.retrieval.get_unified_memory", return_value=object()):
            with patch("magi.context.retrieval.HybridRetrievalService") as service_cls:
                service_cls.return_value.query = AsyncMock(
                    side_effect=[detail_payload, summary_payload, experience_payload]
                )

                payload = await service.build_retrieved_memory_payload(
                    user_id="u1",
                    session_id="s1",
                    task_category="chat",
                )

        self.assertEqual(payload["l0_workbench"][0]["summary"], "Current goal")
        self.assertEqual(payload["l2_entity_cards"][0]["entity_id"], "user:u1")
        self.assertEqual(payload["l3_reflection_memory"][0]["summary"], "User wants to switch jobs")
        self.assertEqual(payload["l4_procedural_memory"][0]["skill_name"], "browser.open")