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
        context_text: str = "",
        workspace_path: str | None = None,
        allowed_layers: tuple[str, ...] = ("L0",),
    ) -> dict[str, Any]:
        if self._unified_memory is None:
            return self._empty_payload()

        normalized_layers = self._normalize_allowed_layers(allowed_layers)
        task_preferences = await self._load_l4_task_preferences(
            user_id=user_id,
            task_category=task_category,
        )
        if normalized_layers == ("L0",):
            return {
                "l0_workbench": await self._load_l0_workbench(session_id),
                "l2_entity_cards": [],
                "l3_reflection_memory": [],
                "l4_procedural_memory": task_preferences,
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
                context_signals={
                    "workspace_path": workspace_path,
                    "user_text": context_text or query,
                    "task_category": task_category,
                },
                limit=10,
            )
        )

        return {
            "l0_workbench": payload.l0_workbench if "L0" in normalized_layers else [],
            "l2_entity_cards": payload.l2_entity_cards if "L2" in normalized_layers else [],
            "l3_reflection_memory": payload.l3_reflections if "L3" in normalized_layers else [],
            "l4_procedural_memory": self._merge_l4_procedures(
                payload.l4_procedures if "L4" in normalized_layers else [],
                task_preferences,
            ),
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
        normalized = tuple(
            str(layer).strip().upper() for layer in allowed_layers if str(layer).strip()
        )
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

    async def _load_l4_task_preferences(
        self,
        *,
        user_id: str,
        task_category: str,
    ) -> list[dict[str, Any]]:
        l4 = getattr(self._unified_memory, "l4", None) if self._unified_memory is not None else None
        if l4 is None or not hasattr(l4, "get_task_preferences"):
            return []
        try:
            return list(
                await l4.get_task_preferences(
                    user_id=user_id,
                    task_category=task_category,
                    limit=4,
                )
            )
        except Exception:
            return []

    @staticmethod
    def _merge_l4_procedures(
        retrieved: list[dict[str, Any]],
        task_preferences: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in [*task_preferences, *list(retrieved or [])]:
            if not isinstance(item, dict):
                continue
            key = str(item.get("skill_id") or item.get("summary") or item.get("content") or item)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result
