"""Context-layer retrieval helpers for prompt assembly."""

from __future__ import annotations

from typing import Any

from ..memory.hybrid_retrieval import HybridRetrievalService, build_query


class ContextRetrievalService:
    """Own retrieval payload construction for prompt/context assembly."""

    def __init__(self, unified_memory: Any = None) -> None:
        self._unified_memory = unified_memory

    async def build_retrieved_memory_payload(
        self,
        *,
        user_id: str,
        session_id: str | None,
        task_category: str,
    ) -> dict[str, Any]:
        if self._unified_memory is None:
            return {
                "l0_workbench": [],
                "l2_entity_cards": [],
                "l3_reflection_memory": [],
                "l4_procedural_memory": [],
                "preference_memory": {},
            }

        retrieval = HybridRetrievalService(self._unified_memory)
        detail_payload = await retrieval.query(
            build_query(
                query=task_category,
                user_id=user_id,
                session_id=session_id,
                time_range={},
                query_mode="detail",
                source_filters=[],
                domain_filters=[],
                limit=5,
            )
        )
        summary_payload = await retrieval.query(
            build_query(
                query=task_category,
                user_id=user_id,
                session_id=session_id,
                time_range={},
                query_mode="summary",
                source_filters=[],
                domain_filters=[],
                limit=3,
            )
        )
        experience_payload = await retrieval.query(
            build_query(
                query=task_category,
                user_id=user_id,
                session_id=session_id,
                time_range={},
                query_mode="experience",
                source_filters=[],
                domain_filters=[],
                limit=3,
            )
        )
        return {
            "l0_workbench": detail_payload.l0_workbench,
            "l2_entity_cards": detail_payload.l2_entity_cards,
            "l3_reflection_memory": summary_payload.l3_reflections,
            "l4_procedural_memory": experience_payload.l4_procedures,
            "preference_memory": {},
        }