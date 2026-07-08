"""L2 control-plane operations for the unified memory store."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional

from magi.identity.defaults import CANONICAL_LOCAL_USER

from ..core.sqlite import sqlite_connection_async


_CANONICAL_SELF_ENTITY_ID = f"user:{CANONICAL_LOCAL_USER}"


def _canonicalize_user_entity_ref(value: Any) -> str:
    text = str(value or "").strip()
    if text == "user:self":
        return _CANONICAL_SELF_ENTITY_ID
    return text


class UnifiedMemoryL2OperationsMixin:
    """Expose L2 replay, reconcile, snapshot, and graph-write controls."""

    l1: Any
    l2: Any
    l2_pipeline: Any
    _edge_embedding_drainer: Any

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

    async def drain_l2_edge_embeddings(
        self,
        *,
        batch_limit: int = 200,
        max_batches: int = 1000,
    ) -> int:
        """Synchronously embed pending L2 knowledge-graph edges."""
        drainer = getattr(self, "_edge_embedding_drainer", None)
        if drainer is None:
            return 0
        total = 0
        normalized_limit = max(1, int(batch_limit))
        for _ in range(max(1, int(max_batches))):
            count = int(await drainer.drain_once(batch_limit=normalized_limit) or 0)
            total += count
            if count < normalized_limit:
                break
        return total

    async def get_l2_edge_embedding_backlog(self) -> dict[str, int]:
        """Return pending L2 edge embedding counts."""
        if self.l2 is None:
            return {"pending": 0}
        async with sqlite_connection_async(self.l2.db_path) as db:
            async with db.execute(
                """
                SELECT COUNT(*)
                FROM knowledge_graph
                WHERE embedding_status = 'pending'
                  AND status = 'active'
                """
            ) as cursor:
                row = await cursor.fetchone()
        return {"pending": int(row[0] if row is not None else 0)}

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
            subject_id=_canonicalize_user_entity_ref(subject_id),
            subject_type=subject_type,
            predicate=predicate,
            object_id=_canonicalize_user_entity_ref(object_id),
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
                "subject_id": _canonicalize_user_entity_ref(edge["subject_id"]),
                "subject_type": str(edge["subject_type"]),
                "predicate": str(edge["predicate"]),
                "object_id": _canonicalize_user_entity_ref(edge["object_id"]),
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
