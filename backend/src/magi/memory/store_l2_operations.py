"""L2 control-plane operations for the unified memory store."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional


class UnifiedMemoryL2OperationsMixin:
    """Expose L2 replay, reconcile, snapshot, and graph-write controls."""

    l1: Any
    l2: Any
    l2_pipeline: Any

    async def replay_l2_extraction(self, event_id: str) -> bool:
        """Replay L2 extraction for an already stored L1 event."""
        if self.l1 is None or self.l2_pipeline is None:
            return False
        event = await self.l1.get_memory_event(event_id)
        if event is None:
            return False
        return await self.l2_pipeline.enqueue_event(event)

    async def reconcile_entities(self, entity_ids: list[str]) -> bool:
        """Trigger entity-level reconcile for one or more entities."""
        if self.l2_pipeline is None:
            return False
        return await self.l2_pipeline.enqueue_entities(entity_ids)

    async def refresh_l2_snapshots(self, entity_ids: list[str]) -> bool:
        """Trigger snapshot materialization for one or more entities."""
        if self.l2_pipeline is None:
            return False
        return await self.l2_pipeline.enqueue_snapshot_refresh(entity_ids)

    async def flush_l2_microbatches(self) -> int:
        """Flush all currently staged L2 microbatches into extract jobs."""
        if self.l2_pipeline is None:
            return 0
        return await self.l2_pipeline.flush_all_pending_batches()

    async def on_session_end(self, session_id: str) -> list[str]:
        """Flush staged L2 session work and enqueue touched-entity reconciliation."""
        if not session_id or self.l2_pipeline is None:
            return []
        return await self.l2_pipeline.flush_session(session_id)

    async def upsert_user_graph_edge(
        self,
        *,
        subject_id: str,
        subject_type: str,
        predicate: str,
        object_id: str,
        object_type: str,
        fact_kind: str | None = None,
        evidence_event_ids: list[str],
        confidence: float,
        observed_at: float,
        source_type: str,
        subject_attributes: Optional[Dict[str, Any]] = None,
        object_attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write a knowledge-graph edge through the unified cognition store."""
        _ = subject_attributes
        _ = object_attributes
        if self.l2 is None:
            return
        await self.l2.upsert_knowledge_edge(
            subject_id=subject_id,
            subject_type=subject_type,
            predicate=predicate,
            object_id=object_id,
            object_type=object_type,
            fact_kind=fact_kind,
            evidence_event_ids=evidence_event_ids,
            confidence=confidence,
            observed_at=observed_at,
            source_type=source_type,
        )

    async def upsert_user_graph_edges(self, edges: Iterable[Mapping[str, Any]]) -> list[str]:
        """Write multiple knowledge-graph edges through one cognition-store batch."""
        if self.l2 is None:
            return []

        edge_writes = [
            {
                "subject_id": str(edge["subject_id"]),
                "subject_type": str(edge["subject_type"]),
                "predicate": str(edge["predicate"]),
                "object_id": str(edge["object_id"]),
                "object_type": str(edge["object_type"]),
                "fact_kind": edge.get("fact_kind"),
                "evidence_event_ids": [str(item) for item in edge.get("evidence_event_ids", [])],
                "confidence": float(edge["confidence"]),
                "observed_at": float(edge["observed_at"]),
                "source_type": str(edge["source_type"]),
            }
            for edge in edges
        ]
        if not edge_writes:
            return []
        return await self.l2.upsert_knowledge_edges(edge_writes)


__all__ = ["UnifiedMemoryL2OperationsMixin"]
