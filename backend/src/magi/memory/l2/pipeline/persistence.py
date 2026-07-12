"""Persistence helpers for L2Pipeline extraction outputs."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol, cast

from ....core.logger import get_logger
from ...event_contracts import MemoryEvent

if TYPE_CHECKING:
    from ..store import L2CognitionStore

logger = get_logger(__name__)


class _L2PipelinePersistenceHostProtocol(Protocol):
    _cognition_store: L2CognitionStore | None

    async def _acquire_entity_locks(self, entity_ids: list[str]) -> list[asyncio.Lock]: ...


class L2PipelinePersistenceMixin:
    """Write prepared graph, facet, assertion, and contradiction outputs."""

    async def _direct_write_graph_candidates(
        self,
        *,
        event: MemoryEvent,
        candidates: list[dict[str, Any]],
    ) -> int:
        count = await self._upsert_knowledge_edges(candidates)
        if count > 0:
            logger.debug(
                "L2 structured hints direct-written before Phase 1",
                event_id=event.event_id,
                direct_write_count=count,
            )
        return count

    async def _upsert_knowledge_edges(self, candidates: list[dict[str, Any]]) -> int:
        host = self._persistence_host()
        if not candidates or host._cognition_store is None:
            return 0

        count = 0
        for candidate in candidates:
            await host._cognition_store.upsert_knowledge_edge(**candidate)
            count += 1
        return count

    async def _upsert_entity_facets(self, candidates: list[dict[str, Any]]) -> int:
        host = self._persistence_host()
        if not candidates or host._cognition_store is None:
            return 0

        count = 0
        for candidate in candidates:
            await host._cognition_store.upsert_entity_facet(**candidate)
            count += 1
        return count

    async def _persist_extraction_outputs(
        self,
        *,
        graph_candidates: list[dict[str, Any]],
        direct_write_candidates: list[dict[str, Any]],
        facet_candidates: list[dict[str, Any]],
        assertion_candidates: list[dict[str, Any]],
        contradiction_hints: list[Any],
    ) -> tuple[int, int, int]:
        host = self._persistence_host()
        if host._cognition_store is None:
            return (0, 0, 0)

        persist_entity_ids = sorted(
            {
                str(candidate.get("subject_id", ""))
                for candidate in graph_candidates + direct_write_candidates
                if candidate.get("subject_id")
            }
            | {
                str(candidate.get("object_id", ""))
                for candidate in graph_candidates + direct_write_candidates
                if candidate.get("object_id")
            }
            | {
                str(candidate.get("entity_id", ""))
                for candidate in assertion_candidates
                if candidate.get("entity_id")
            }
        )
        entity_locks = await host._acquire_entity_locks(persist_entity_ids)
        try:
            relation_count = await self._upsert_knowledge_edges(graph_candidates)
            facet_count = await self._upsert_entity_facets(facet_candidates)

            assertion_count = 0
            for candidate in assertion_candidates:
                await host._cognition_store.upsert_assertion_candidate(candidate)
                assertion_count += 1

            for hint in contradiction_hints:
                await host._cognition_store.apply_contradiction_hint(hint)
        finally:
            for lock in entity_locks:
                lock.release()

        return (relation_count, facet_count, assertion_count)

    def _persistence_host(self) -> _L2PipelinePersistenceHostProtocol:
        return cast(_L2PipelinePersistenceHostProtocol, self)


__all__ = ["L2PipelinePersistenceMixin"]
