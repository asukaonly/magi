"""Entity catalog and alias-resolution helpers for L2 cognition."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

import aiosqlite

from ...config.models import EmbeddingBackend
from ...core.sqlite import sqlite_connection_async
from ..embedding.chunking import ChunkedText
from ..embedding.embedding_pipeline import EmbeddingPipelineItem, MemoryEmbeddingPipeline
from ..embedding.embedding_service import EmbeddingProfile
from ..embedding.embedding_text_builders import build_l2_entity_embedding_text
from ..embedding.embedding_service import MemoryEmbeddingService
from ..embedding.sqlite_vec_index import SqliteVecIndex
from .ontology import coerce_unknown_entity_type

logger = logging.getLogger(__name__)

EMBEDDING_TEXT_BUILDER_VERSION = "l2_entity_v1"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_DISABLED = "disabled"


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


class L2EntityCatalog:
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

    async def initialize(self) -> None:
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS entity_catalog (
                    entity_id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    embedding_status TEXT NOT NULL DEFAULT 'disabled',
                    embedding_profile_id TEXT,
                    last_embedded_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_entity_catalog_type ON entity_catalog(entity_type);

                CREATE TABLE IF NOT EXISTS entity_aliases (
                    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    alias_text TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(entity_id, normalized_alias),
                    FOREIGN KEY(entity_id) REFERENCES entity_catalog(entity_id)
                );
                CREATE INDEX IF NOT EXISTS idx_entity_aliases_lookup ON entity_aliases(normalized_alias, confidence DESC);

                CREATE TABLE IF NOT EXISTS entity_mentions (
                    mention_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mention_text TEXT NOT NULL,
                    normalized_surface TEXT NOT NULL,
                    entity_type TEXT,
                    evidence_event_ids TEXT NOT NULL,
                    evidence_text TEXT,
                    resolved_entity_id TEXT,
                    confidence REAL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(resolved_entity_id) REFERENCES entity_catalog(entity_id)
                );
                CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity ON entity_mentions(resolved_entity_id);
                """
            )
            await db.commit()
        self._initialized = True

    async def close(self) -> None:
        if self._vector_index is not None:
            await self._vector_index.close()
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
        normalized_resolved_entity_id = _normalize_entity_ref(resolved_entity_id, normalized_entity_type)
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

    async def list_entities(
        self,
        *,
        limit: int = 100,
        entity_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        await self.initialize()
        if entity_ids is not None and not entity_ids:
            return []
        return await self._list_entities(limit=limit, entity_ids=entity_ids)

    async def list_mentions(self, *, limit: int = 100) -> list[dict[str, Any]]:
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT mention_id, mention_text, normalized_surface, entity_type,
                       evidence_event_ids, evidence_text, resolved_entity_id, confidence
                FROM entity_mentions
                ORDER BY mention_id DESC
                LIMIT ?
                """,
                (int(limit),),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            {
                "mention_id": int(row["mention_id"]),
                "mention_text": str(row["mention_text"]),
                "normalized_surface": str(row["normalized_surface"]),
                "entity_type": row["entity_type"],
                "evidence_event_ids": json.loads(row["evidence_event_ids"] or "[]"),
                "evidence_text": row["evidence_text"],
                "resolved_entity_id": row["resolved_entity_id"],
                "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
            }
            for row in rows
        ]

    async def list_entities_by_type(self, *, entity_type: str, limit: int = 100, order_by_recency: bool = False) -> list[dict[str, Any]]:
        await self.initialize()
        return await self._list_entities(limit=limit, entity_type=_normalize_catalog_entity_type(entity_type), order_by_recency=order_by_recency)

    async def find_by_canonical_name(
        self,
        canonical_name: str,
        *,
        entity_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return catalog entries matching *canonical_name* (case-insensitive)."""
        await self.initialize()
        normalized_name = canonical_name.strip().casefold()
        if not normalized_name:
            return []
        query = """
            SELECT entity_id, canonical_name, entity_type
            FROM entity_catalog
            WHERE LOWER(canonical_name) = ?
        """
        args: list[Any] = [normalized_name]
        if entity_type:
            normalized_type = _normalize_catalog_entity_type(entity_type)
            query += " AND entity_type = ?"
            args.append(normalized_type)
        query += " ORDER BY updated_at DESC LIMIT 10"
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [
            {
                "entity_id": str(row["entity_id"]),
                "canonical_name": str(row["canonical_name"]),
                "entity_type": str(row["entity_type"]),
            }
            for row in rows
        ]

    async def resolve_query_entities(
        self,
        query_text: str,
        *,
        limit: int = 10,
        entity_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Resolve natural-language query text into matching canonical entities.

        Uses text substring matching, supplemented by vector similarity when
        an embedding model is available and L2 vectors are enabled.
        """
        await self.initialize()
        normalized_query = _normalize_alias(query_text)
        if not normalized_query:
            return []

        type_filter = {
            normalized
            for item in (entity_types or [])
            if (normalized := _normalize_catalog_entity_type(item))
        }

        matches = await self._search_entities_by_substring(
            normalized_query,
            type_filter=type_filter or None,
        )

        # Merge vector similarity results when available
        semantic_hits = await self.search_entities_semantic(query_text, limit=limit)
        text_match_ids = {str(m["entity_id"]) for m in matches}
        for hit in semantic_hits:
            entity_id = str(hit["entity_id"])
            if entity_id in text_match_ids:
                continue
            entity_type = str(hit.get("entity_type") or "").strip()
            if type_filter and entity_type not in type_filter:
                continue
            matches.append(
                {
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "canonical_name": str(hit.get("canonical_name") or ""),
                    "match_source": "vector",
                    "matched_text": str(hit.get("canonical_name") or ""),
                    "confidence": 0.8,
                }
            )

        matches.sort(
            key=lambda item: (
                -len(str(item.get("matched_text") or "")),
                -float(item.get("confidence", 0.0) or 0.0),
                str(item.get("entity_id") or ""),
            )
        )
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in matches:
            entity_id = str(item["entity_id"])
            if entity_id in seen:
                continue
            seen.add(entity_id)
            deduped.append(item)
            if len(deduped) >= int(limit):
                break
        return deduped

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
        return count

    async def rebuild_embeddings(self, *, batch_size: int = 100) -> int:
        """Rebuild all L2 entity vectors from canonical catalog rows."""
        await self.initialize()
        normalized_batch_size = max(1, int(batch_size))
        if not self._vectors_enabled() or self._embedding_service is None or self._vector_index is None:
            return 0

        await self._vector_index.clear()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                UPDATE entity_catalog
                SET embedding_status = ?, embedding_profile_id = NULL, last_embedded_at = NULL
                """,
                (EMBEDDING_STATUS_DISABLED,),
            )
            await db.commit()

        processed = 0
        offset = 0
        while True:
            async with sqlite_connection_async(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """
                    SELECT entity_id
                    FROM entity_catalog
                    ORDER BY updated_at DESC, entity_id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (normalized_batch_size, offset),
                ) as cursor:
                    rows = await cursor.fetchall()
            if not rows:
                break
            entity_ids = [str(row["entity_id"]) for row in rows]
            for entity_id in entity_ids:
                await self._maybe_embed_entity(entity_id)
            processed += len(entity_ids)
            offset += len(rows)
        return processed

    # ------------------------------------------------------------------
    # Vector helpers
    # ------------------------------------------------------------------

    def _vectors_enabled(self) -> bool:
        if self._embedding_service is None:
            return False
        config = self._current_memory_config()
        if config is None:
            return self._default_vector_enabled
        return bool(
            config.embedding.backend == EmbeddingBackend.SQLITE_VEC
            and config.l2.enabled
            and config.l2.vectors_enabled
        )

    def _current_memory_config(self) -> Any:
        if self._memory_config_getter is None:
            return None
        try:
            return self._memory_config_getter()
        except Exception:
            return None

    async def _maybe_embed_entity(self, entity_id: str) -> None:
        if not self._vectors_enabled():
            return
        pipeline = self._build_embedding_pipeline()
        if pipeline is None:
            return
        try:
            text = await self._build_entity_embedding_text(entity_id)
            if not text:
                return
            results = await pipeline.upsert_items(
                [
                    EmbeddingPipelineItem(
                        parent_id=entity_id,
                        chunks=[
                            ChunkedText(
                                chunk_id=entity_id,
                                text=text,
                                chunk_index=0,
                                char_start=0,
                                char_end=len(text),
                                token_estimate=max(1, len(text) // 4),
                            )
                        ],
                        metadata={"kind": "entity"},
                    )
                ]
            )
            if not results:
                return
            profile = self._profile_from_embedding_result(results[0].embeddings[0])
            await self._update_entity_embedding_state(
                entity_id=entity_id,
                status=EMBEDDING_STATUS_READY,
                profile_id=profile.profile_id,
                embedded_at=results[0].embedded_at,
            )
        except Exception as exc:
            logger.debug("Failed to embed L2 entity %s: %s", entity_id, exc)

    def _build_embedding_pipeline(self) -> MemoryEmbeddingPipeline | None:
        if self._embedding_service is None or self._vector_index is None:
            return None
        return MemoryEmbeddingPipeline(
            embedding_service=self._embedding_service,
            vector_index=self._vector_index,
        )

    async def _build_entity_embedding_text(self, entity_id: str) -> str:
        entities = await self._list_entities(limit=1, entity_ids=[entity_id])
        if not entities:
            return ""
        entity = entities[0]
        return build_l2_entity_embedding_text(
            canonical_name=str(entity.get("canonical_name") or ""),
            entity_type=str(entity.get("entity_type") or ""),
            aliases=[str(alias) for alias in entity.get("aliases", [])],
        )

    def _profile_from_embedding_result(self, result) -> EmbeddingProfile:
        getter = getattr(self._embedding_service, "profile_from_result", None)
        if callable(getter):
            return getter(result, text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION)
        return EmbeddingProfile.build(
            provider_name="unknown",
            model_name=result.model_name,
            dimension=result.dimension,
            text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
        )

    async def _update_entity_embedding_state(
        self,
        *,
        entity_id: str,
        status: str,
        profile_id: str | None,
        embedded_at: float | None,
    ) -> None:
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                UPDATE entity_catalog
                SET embedding_status = ?, embedding_profile_id = ?, last_embedded_at = ?, updated_at = updated_at
                WHERE entity_id = ?
                """,
                (status, profile_id, embedded_at, entity_id),
            )
            await db.commit()

    async def search_entities_semantic(
        self,
        query_text: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search entities using vector similarity. Returns [] if vectors are disabled."""
        if not self._vectors_enabled() or self._embedding_service is None or self._vector_index is None:
            return []
        query_text = query_text.strip()
        if not query_text:
            return []
        try:
            embedding = await self._embedding_service.embed_text(query_text)
            if embedding is None:
                return []
            hits = await self._vector_index.search(embedding=embedding, limit=limit)
        except Exception as exc:
            logger.debug("L2 entity semantic search failed: %s", exc)
            return []
        if not hits:
            return []

        hit_ids = [hit.entity_id for hit in hits]
        distance_by_id = {hit.entity_id: hit.distance for hit in hits}
        entities = await self._list_entities(limit=len(hit_ids), entity_ids=hit_ids)
        for entity in entities:
            entity["distance"] = distance_by_id.get(entity["entity_id"])
        entities.sort(key=lambda e: e.get("distance") or float("inf"))
        return entities[:limit]

    async def _search_entities_by_substring(
        self,
        normalized_query: str,
        *,
        type_filter: set[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Find entities whose canonical name or alias is a substring of the query.

        Uses SQL INSTR() to avoid loading all entities into Python.
        """
        type_clause = ""
        type_args: list[Any] = []
        if type_filter:
            type_ph = ", ".join("?" for _ in type_filter)
            type_clause = f" AND ec.entity_type IN ({type_ph})"
            type_args = list(type_filter)

        query = f"""
            SELECT ec.entity_id, ec.canonical_name, ec.entity_type,
                   ec.canonical_name AS matched_text, 'canonical_name' AS match_source
            FROM entity_catalog ec
            WHERE INSTR(?, LOWER(TRIM(ec.canonical_name))) > 0{type_clause}
            UNION ALL
            SELECT ec.entity_id, ec.canonical_name, ec.entity_type,
                   ea.alias_text AS matched_text, 'alias' AS match_source
            FROM entity_aliases ea
            JOIN entity_catalog ec ON ea.entity_id = ec.entity_id
            WHERE INSTR(?, ea.normalized_alias) > 0{type_clause}
              AND ec.entity_id NOT IN (
                  SELECT entity_id FROM entity_catalog
                  WHERE INSTR(?, LOWER(TRIM(canonical_name))) > 0
              )
            LIMIT ?
        """
        args = [normalized_query] + type_args + [normalized_query] + type_args + [normalized_query, limit]

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        matches: list[dict[str, Any]] = []
        for row in rows:
            match_source = str(row["match_source"])
            matches.append({
                "entity_id": str(row["entity_id"]),
                "entity_type": str(row["entity_type"]),
                "canonical_name": str(row["canonical_name"]),
                "match_source": match_source,
                "matched_text": str(row["matched_text"]),
                "confidence": 0.95 if match_source == "canonical_name" else 0.9,
            })
        return matches

    async def _list_entities(
        self,
        *,
        limit: int,
        entity_type: Optional[str] = None,
        entity_ids: list[str] | None = None,
        order_by_recency: bool = False,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT entity_id, canonical_name, entity_type, embedding_status, embedding_profile_id, last_embedded_at
            FROM entity_catalog
        """
        args: list[Any] = []
        conditions: list[str] = []
        if entity_type:
            conditions.append("entity_type = ?")
            args.append(entity_type)
        if entity_ids is not None:
            placeholders = ", ".join("?" for _ in entity_ids)
            conditions.append(f"entity_id IN ({placeholders})")
            args.extend(entity_ids)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        if order_by_recency:
            query += " ORDER BY updated_at DESC LIMIT ?"
        else:
            query += " ORDER BY entity_id ASC LIMIT ?"
        args.append(int(limit))

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                query,
                tuple(args),
            ) as cursor:
                entities = await cursor.fetchall()

            async with db.execute(
                """
                SELECT entity_id, alias_text
                FROM entity_aliases
                ORDER BY normalized_alias ASC
                """
            ) as cursor:
                alias_rows = await cursor.fetchall()

        aliases_by_entity: dict[str, list[str]] = {}
        for row in alias_rows:
            aliases_by_entity.setdefault(str(row["entity_id"]), []).append(str(row["alias_text"]))

        return [
            {
                "entity_id": str(row["entity_id"]),
                "canonical_name": str(row["canonical_name"]),
                "entity_type": str(row["entity_type"]),
                "embedding_status": str(row["embedding_status"] or EMBEDDING_STATUS_DISABLED),
                "embedding_profile_id": row["embedding_profile_id"],
                "last_embedded_at": float(row["last_embedded_at"]) if row["last_embedded_at"] is not None else None,
                "aliases": aliases_by_entity.get(str(row["entity_id"]), []),
            }
            for row in entities
        ]


__all__ = ["L2EntityCatalog"]
