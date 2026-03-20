"""Context-layer retrieval helpers for prompt assembly."""

from __future__ import annotations

from typing import Any

from ..memory.hybrid_retrieval import build_query


class ContextRetrievalService:
    """Own retrieval payload construction for prompt/context assembly."""

    def __init__(self, unified_memory: Any = None, retrieval_service: Any = None) -> None:
        self._unified_memory = unified_memory
        self._retrieval_service = retrieval_service

    async def build_retrieved_memory_payload(
        self,
        *,
        user_id: str,
        session_id: str | None,
        query: str,
        task_category: str,
        allowed_layers: tuple[str, ...] = ("L0",),
    ) -> dict[str, Any]:
        if self._unified_memory is None:
            return self._empty_payload()

        normalized_layers = self._normalize_allowed_layers(allowed_layers)
        if normalized_layers == ("L0",):
            return {
                "l0_workbench": await self._load_l0_workbench(session_id),
                "l2_entity_cards": [],
                "l3_reflection_memory": [],
                "l4_procedural_memory": [],
                "preference_memory": {},
            }

        if self._retrieval_service is None:
            raise RuntimeError("hybrid retrieval service is not initialized")

        payload = await self._retrieval_service.query(
            build_query(
                query=query,
                user_id=user_id,
                session_id=session_id,
                time_range={},
                query_mode=None,
                source_filters=[],
                domain_filters=[],
                limit=10,
            )
        )

        return {
            "l0_workbench": payload.l0_workbench if "L0" in normalized_layers else [],
            "l2_entity_cards": payload.l2_entity_cards if "L2" in normalized_layers else [],
            "l3_reflection_memory": payload.l3_reflections if "L3" in normalized_layers else [],
            "l4_procedural_memory": payload.l4_procedures if "L4" in normalized_layers else [],
            "preference_memory": {},
        }

    @staticmethod
    def _empty_payload() -> dict[str, Any]:
        return {
            "l0_workbench": [],
            "l2_entity_cards": [],
            "l3_reflection_memory": [],
            "l4_procedural_memory": [],
            "preference_memory": {},
        }

    @staticmethod
    def _normalize_allowed_layers(allowed_layers: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        normalized = tuple(str(layer).strip().upper() for layer in allowed_layers if str(layer).strip())
        return normalized or ("L0",)

    async def _load_l0_workbench(self, session_id: str | None) -> list[dict[str, Any]]:
        if not session_id or getattr(self._unified_memory, "l0", None) is None:
            return []
        try:
            workbench = await self._unified_memory.l0.get_workbench(session_id)
        except Exception:
            return []
        if not isinstance(workbench, dict) or workbench.get("session") is None:
            return []
        return [
            {
                "session": workbench["session"],
                "goals": list(workbench.get("goal_stack", [])[:3]),
                "active_entities": list(workbench.get("active_entities", [])[:5]),
                "temporary_tactics": list(workbench.get("temporary_tactics", [])[:5]),
            }
        ]
