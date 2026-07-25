from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from magi.context.retrieval import ContextRetrievalService


class _FakeL0Store:
    async def get_prompt_workbench_projection(self, session_id: str):
        class _Projection:
            @staticmethod
            def to_retrieval_entry():
                return {
                    "session": session_id,
                    "goals": ["ship the fix"],
                    "active_entities": ["repo:magi"],
                    "temporary_tactics": ["stay small"],
                    "execution_summary": {
                        "active_run_summary": "ship the fix",
                    },
                }

        return _Projection()


class _FakeL4Store:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    async def get_task_preferences(self, **kwargs):
        self.calls.append(dict(kwargs))
        return [
            {
                "skill_id": "task-pref-1",
                "skill_name": "coding preference",
                "skill_category": "task_preference",
                "summary": "Prefer: 改代码前先讲完成标准",
            }
        ]


class _FakeUnifiedMemory:
    def __init__(self):
        self.l0 = _FakeL0Store()
        self.l4 = _FakeL4Store()


class TestContextRetrievalService(unittest.IsolatedAsyncioTestCase):
    async def test_build_retrieved_memory_payload_loads_l0_and_task_preferences_without_hybrid_query(
        self,
    ) -> None:
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
        self.assertEqual(
            payload["l0_workbench"][0]["execution_summary"]["active_run_summary"],
            "ship the fix",
        )
        self.assertEqual(payload["l2_entity_cards"], [])
        self.assertEqual(payload["l3_reflection_memory"], [])
        self.assertEqual(
            payload["l4_procedural_memory"][0]["summary"], "Prefer: 改代码前先讲完成标准"
        )
        retrieval_service.query.assert_not_called()

    async def test_build_retrieved_memory_payload_appends_task_preferences_from_l4(self) -> None:
        unified_memory = _FakeUnifiedMemory()
        service = ContextRetrievalService(
            unified_memory=unified_memory,
            retrieval_service=MagicMock(),
        )

        payload = await service.build_retrieved_memory_payload(
            user_id="u1",
            session_id="s1",
            query="fix this bug",
            task_category="coding",
            allowed_layers=("L0",),
        )

        self.assertEqual(
            unified_memory.l4.calls,
            [{"user_id": "u1", "task_category": "coding", "limit": 4}],
        )
        self.assertEqual(payload["l4_procedural_memory"][0]["skill_category"], "task_preference")

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
            context_text="I meant this repository",
            workspace_path="/work/magi",
            allowed_layers=("L0", "L4"),
        )

        retrieval_service.query.assert_called_once()
        request = retrieval_service.query.call_args.args[0]
        self.assertEqual(request.context_signals.workspace_path, "/work/magi")
        self.assertEqual(request.context_signals.user_text, "I meant this repository")
        self.assertEqual(request.context_signals.task_category, "chat")

        self.assertEqual(payload["l0_workbench"][0]["summary"], "Current goal")
        self.assertEqual(payload["l2_entity_cards"], [])
        self.assertEqual(payload["l3_reflection_memory"], [])
        self.assertEqual(payload["l4_procedural_memory"][0]["skill_name"], "browser.open")

    async def test_build_retrieved_memory_payload_requires_injected_service_for_hybrid_queries(
        self,
    ) -> None:
        service = ContextRetrievalService(unified_memory=object(), retrieval_service=None)

        with self.assertRaises(RuntimeError):
            await service.build_retrieved_memory_payload(
                user_id="u1",
                session_id="s1",
                query="switch jobs",
                task_category="chat",
                allowed_layers=("L0", "L3"),
            )
