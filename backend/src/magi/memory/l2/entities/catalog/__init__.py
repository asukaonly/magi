"""Entity catalog and alias-resolution helpers for L2 cognition."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

import aiosqlite

from .....core.sqlite import sqlite_connection_async
from ....embedding.embedding_service import MemoryEmbeddingService
from ....embedding.sqlite_vec_index import SqliteVecIndex
from .embeddings import (
    EMBEDDING_STATUS_DISABLED,
    EMBEDDING_STATUS_READY,
    EMBEDDING_TEXT_BUILDER_VERSION,
    L2EntityCatalogEmbeddingMixin,
)
from .queries import L2EntityCatalogQueryMixin
from ...ontology import coerce_unknown_entity_type

logger = logging.getLogger(__name__)


def _normalize_alias(text: str) -> str:
    return text.strip().casefold()


def _normalize_catalog_entity_type(entity_type: Optional[str]) -> Optional[str]:
    if entity_type is None:
        return None
    return coerce_unknown_entity_type(entity_type)


def _normalize_entity_ref(entity_id: Optional[str], entity_type: Optional[str]) -> Optional[str]:
    if entity_id is None:
        return None
    text = entity_id.strip()
    if not text or not entity_type or ":" not in text:
        return text or None
    _, _, suffix = text.partition(":")
    if not suffix:
        return text
    return f"{entity_type}:{suffix}"


class L2EntityCatalog(L2EntityCatalogQueryMixin, L2EntityCatalogEmbeddingMixin):
    """Stores canonical entities, aliases, and mention evidence."""

    def __init__(
        self,
        *,
        db_path: str = "~/.magi/data/memory/memory.db",
        embedding_service: MemoryEmbeddingService | None = None,
        memory_config_getter: Callable[[], Any] | None = None,
        vector_enabled: bool = True,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._embedding_service = embedding_service
        self._memory_config_getter = memory_config_getter
        self._default_vector_enabled = bool(vector_enabled and embedding_service is not None)
        self._vector_index = (
            SqliteVecIndex(
                db_path=self.db_path,
                registry_table="l2_entity_vectors",
                entity_column="entity_id",
                vec_table_prefix="l2_entity_vec",
            )
            if embedding_service is not None or vector_enabled
            else None
        )
        self._initialized = False

    @property
    def embedding_service(self) -> MemoryEmbeddingService | None:
        """Public access to the embedding service used by this catalog."""
        return self._embedding_service

    @property
    def edge_vector_index(self) -> SqliteVecIndex | None:
        """Return a vector index for L2 edge embeddings, or None."""
        if self._embedding_service is None:
            return None
        if not hasattr(self, "_edge_vector_index"):
            self._edge_vector_index = SqliteVecIndex(
                db_path=self.db_path,
                registry_table="l2_edge_vectors",
                entity_column="entity_id",
                vec_table_prefix="l2_edge_vec",
            )
        return self._edge_vector_index

    async def initialize(self) -> None:
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialized = True

    async def close(self) -> None:
        if self._vector_index is not None:
            await self._vector_index.close()
        edge_vector_index = getattr(self, "_edge_vector_index", None)
        if edge_vector_index is not None:
            await edge_vector_index.close()
        self._initialized = False

    async def upsert_entity(
        self,
        *,
        canonical_name: str,
        entity_type: str,
        entity_id: str,
    ) -> str:
        await self.initialize()
        normalized_entity_type = _normalize_catalog_entity_type(entity_type)
        normalized_entity_id = _normalize_entity_ref(entity_id, normalized_entity_type) or entity_id
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO entity_catalog(entity_id, canonical_name, entity_type, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    canonical_name = excluded.canonical_name,
                    entity_type = excluded.entity_type,
                    updated_at = excluded.updated_at
                """,
                (normalized_entity_id, canonical_name, normalized_entity_type, now, now),
            )
            await db.commit()
        await self._maybe_embed_entity(normalized_entity_id)
        return normalized_entity_id

    async def add_alias(self, *, entity_id: str, alias_text: str, confidence: float = 1.0) -> None:
        await self.initialize()
        now = time.time()
        normalized_alias = _normalize_alias(alias_text)
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO entity_aliases(entity_id, alias_text, normalized_alias, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_id, normalized_alias) DO UPDATE SET
                    alias_text = excluded.alias_text,
                    confidence = excluded.confidence,
                    updated_at = excluded.updated_at
                """,
                (entity_id, alias_text, normalized_alias, float(confidence), now, now),
            )
            await db.commit()
        await self._maybe_embed_entity(entity_id)

    async def resolve_alias(
        self,
        alias_text: str,
        *,
        entity_type: Optional[str] = None,
        min_confidence: float = 0.8,
    ) -> dict[str, Any]:
        await self.initialize()
        normalized_alias = _normalize_alias(alias_text)

        query = """
            SELECT c.entity_id, c.entity_type, a.confidence
            FROM entity_aliases a
            JOIN entity_catalog c ON c.entity_id = a.entity_id
            WHERE a.normalized_alias = ?
        """
        args: list[Any] = [normalized_alias]
        normalized_entity_type = _normalize_catalog_entity_type(entity_type)
        if normalized_entity_type:
            query += " AND c.entity_type = ?"
            args.append(normalized_entity_type)
        query += " ORDER BY a.confidence DESC, c.entity_id ASC"

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return {
                "decision": "unresolved",
                "entity_id": None,
                "candidate_count": 0,
                "matched_confidence": None,
            }

        top = rows[0]
        if len(rows) > 1 and float(rows[1]["confidence"]) >= min_confidence:
            return {
                "decision": "unresolved",
                "entity_id": None,
                "candidate_count": len(rows),
                "matched_confidence": float(top["confidence"]),
            }

        if float(top["confidence"]) < min_confidence:
            return {
                "decision": "unresolved",
                "entity_id": None,
                "candidate_count": len(rows),
                "matched_confidence": float(top["confidence"]),
            }

        return {
            "decision": "match",
            "entity_id": str(top["entity_id"]),
            "candidate_count": len(rows),
            "matched_confidence": float(top["confidence"]),
        }

    async def record_mention(
        self,
        *,
        mention_text: str,
        normalized_surface: str,
        entity_type: Optional[str],
        evidence_event_ids: list[str],
        evidence_text: Optional[str],
        resolved_entity_id: Optional[str],
        confidence: Optional[float],
    ) -> int:
        await self.initialize()
        normalized_entity_type = _normalize_catalog_entity_type(entity_type)
        normalized_resolved_entity_id = _normalize_entity_ref(
            resolved_entity_id, normalized_entity_type
        )
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO entity_mentions(
                    mention_text,
                    normalized_surface,
                    entity_type,
                    evidence_event_ids,
                    evidence_text,
                    resolved_entity_id,
                    confidence,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mention_text,
                    normalized_surface,
                    normalized_entity_type,
                    json.dumps(evidence_event_ids, ensure_ascii=False),
                    evidence_text,
                    normalized_resolved_entity_id,
                    float(confidence) if confidence is not None else None,
                    now,
                ),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def get_mention(self, mention_id: int) -> Optional[dict[str, Any]]:
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT mention_id, mention_text, normalized_surface, entity_type,
                       evidence_event_ids, evidence_text, resolved_entity_id, confidence
                FROM entity_mentions
                WHERE mention_id = ?
                """,
                (mention_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "mention_id": int(row["mention_id"]),
            "mention_text": str(row["mention_text"]),
            "normalized_surface": str(row["normalized_surface"]),
            "entity_type": row["entity_type"],
            "evidence_event_ids": json.loads(row["evidence_event_ids"] or "[]"),
            "evidence_text": row["evidence_text"],
            "resolved_entity_id": row["resolved_entity_id"],
            "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
        }

    async def clear(self) -> int:
        """Delete all catalog entities, aliases, and mention evidence."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM entity_catalog) +
                    (SELECT COUNT(*) FROM entity_mentions)
                """
            ) as cursor:
                row = await cursor.fetchone()
                count = int(row[0]) if row else 0
            await db.executescript(
                """
                DELETE FROM entity_mentions;
                DELETE FROM entity_aliases;
                DELETE FROM entity_catalog;
                """
            )
            await db.commit()
        vector_indexes = self._all_vector_indexes_for_clear()
        for vector_index in vector_indexes:
            await vector_index.clear()
        if self._embedding_service is None:
            for vector_index in vector_indexes:
                await vector_index.close()
        return count

    def _all_vector_indexes_for_clear(self) -> list[SqliteVecIndex]:
        """Return both L2 indexes even when vectors are disabled at runtime."""
        if self._vector_index is None:
            self._vector_index = SqliteVecIndex(
                db_path=self.db_path,
                registry_table="l2_entity_vectors",
                entity_column="entity_id",
                vec_table_prefix="l2_entity_vec",
            )
        edge_index = getattr(self, "_edge_vector_index", None)
        if edge_index is None:
            edge_index = SqliteVecIndex(
                db_path=self.db_path,
                registry_table="l2_edge_vectors",
                entity_column="entity_id",
                vec_table_prefix="l2_edge_vec",
            )
            self._edge_vector_index = edge_index
        return [self._vector_index, edge_index]


__all__ = [
    "EMBEDDING_STATUS_DISABLED",
    "EMBEDDING_STATUS_READY",
    "EMBEDDING_TEXT_BUILDER_VERSION",
    "L2EntityCatalog",
]
