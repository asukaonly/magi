"""Knowledge-graph edge embedding helpers for L2 entity maintenance."""

from __future__ import annotations

from typing import Any, Protocol

from .....core.logger import get_logger
from .....core.sqlite import sqlite_connection_async

logger = get_logger("magi.memory.l2.entities.maintenance")


class _EmbeddingMaintenanceStatsProtocol(Protocol):
    edge_embeddings_cleaned: int
    errors: list[str]


class _EmbeddingMaintenanceHostProtocol(Protocol):
    _db_path: str
    _embedding_service: Any | None
    _edge_vector_index: Any | None


class L2EntityEmbeddingMaintenanceMixin:
    """Maintain vector embeddings for active L2 knowledge-graph edges."""

    async def _clean_non_active_edge_embeddings(
        self,
        stats: _EmbeddingMaintenanceStatsProtocol,
    ) -> None:
        """Remove vector embeddings for edges that are no longer 'active'."""
        host = self._embedding_maintenance_host()
        if host._edge_vector_index is None:
            return
        async with sqlite_connection_async(host._db_path) as db:
            async with db.execute("""
                SELECT triple_id FROM knowledge_graph
                WHERE status != 'active' AND embedding_status = 'ready'
                LIMIT 500
                """) as cur:
                rows = await cur.fetchall()
        if not rows:
            return
        for row in rows:
            triple_id = str(row[0])
            try:
                await host._edge_vector_index.delete_entity(entity_id=triple_id)
            except Exception:
                pass
        triple_ids = [str(r[0]) for r in rows]
        placeholders = ", ".join("?" for _ in triple_ids)
        async with sqlite_connection_async(host._db_path) as db:
            await db.execute(
                f"UPDATE knowledge_graph SET embedding_status = 'disabled' WHERE triple_id IN ({placeholders})",
                tuple(triple_ids),
            )
            await db.commit()
        stats.edge_embeddings_cleaned = len(triple_ids)

    def _embedding_maintenance_host(self) -> _EmbeddingMaintenanceHostProtocol:
        return self  # type: ignore[return-value]
