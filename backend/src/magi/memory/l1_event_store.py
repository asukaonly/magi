"""Canonical L1 event store for normalized memory events."""

from __future__ import annotations

import json
import logging
import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite

from ..events.events import Event, EventLevel, EventTypes
from ..timeline.contracts import TimelineEvent
from .embedding_service import MemoryEmbeddingService
from .event_contracts import IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth, normalize_runtime_event
from .hybrid_retrieval.fts_utils import escape_fts_query, tokenize_for_fts
from .sqlite_vec_index import SqliteVecIndex, VectorSearchHit

FACT_EVENTS_TABLE = "fact_events"
RUNTIME_OBSERVATIONS_TABLE = "runtime_observations"
RUNTIME_OBSERVATION_EVENT_TYPES = {
    EventTypes.ACTION_EXECUTED,
    EventTypes.TASK_ASSIGNED,
    EventTypes.TASK_STARTED,
    EventTypes.TASK_COMPLETED,
    EventTypes.TASK_FAILED,
    EventTypes.ERROR_OCCURRED,
    EventTypes.LOOP_STARTED,
    EventTypes.LOOP_PHASE_STARTED,
    "WORKER_AGENT_PROGRESS",
    "WORKER_AGENT_COMPLETED",
    "WORKER_AGENT_FAILED",
    "CHAT_TOOL_LOOP_STEP",
    "TOOL_INTERACTION",
    "TOOL_INVOKED",
    "LLMCallCompleted",
    "Heartbeat",
}

logger = logging.getLogger(__name__)


class L1EventStore:
    """Stores immutable normalized memory events in SQLite."""

    def __init__(
        self,
        *,
        db_path: str = "~/.magi/data/memories/l1_events.db",
        embedding_service: MemoryEmbeddingService | None = None,
        vector_enabled: bool = True,
        async_embeddings: bool = True,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._embedding_service = embedding_service
        self._vector_enabled = bool(vector_enabled and embedding_service is not None)
        self._async_embeddings = bool(async_embeddings)
        self._vector_index = (
            SqliteVecIndex(
                db_path=self.db_path,
                registry_table="l1_event_vectors",
                entity_column="event_id",
                vec_table_prefix="l1_event_vec",
            )
            if self._vector_enabled
            else None
        )
        self._embedding_queue: asyncio.Queue[MemoryEvent | None] | None = asyncio.Queue() if self._vector_enabled and self._async_embeddings else None
        self._embedding_worker: asyncio.Task[None] | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Create the canonical L1 schema."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS fact_events (
                    event_id TEXT PRIMARY KEY,
                    correlation_id TEXT NOT NULL,
                    parent_event_id TEXT,
                    timestamp REAL NOT NULL,
                    created_at REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_item_id TEXT,
                    memory_domain INTEGER NOT NULL,
                    ingest_target INTEGER NOT NULL,
                    cognition_eligible INTEGER NOT NULL DEFAULT 0,
                    tom_depth INTEGER NOT NULL DEFAULT 1,
                    retention_class INTEGER NOT NULL DEFAULT 2,
                    session_id TEXT,
                    user_id TEXT,
                    task_id TEXT,
                    goal_id TEXT,
                    raw_content TEXT NOT NULL,
                    structured_payload TEXT,
                    metadata TEXT,
                    importance_score REAL NOT NULL DEFAULT 0.5,
                    importance_t0_base REAL,
                    importance_t1_score REAL,
                    importance_version INTEGER NOT NULL DEFAULT 1,
                    level INTEGER NOT NULL DEFAULT 1,
                    media_path TEXT,
                    deleted_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_fact_events_timestamp ON fact_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_fact_events_type ON fact_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_fact_events_source ON fact_events(source);
                CREATE INDEX IF NOT EXISTS idx_fact_events_domain ON fact_events(memory_domain);
                CREATE INDEX IF NOT EXISTS idx_fact_events_session ON fact_events(session_id);
                CREATE INDEX IF NOT EXISTS idx_fact_events_user ON fact_events(user_id);
                CREATE INDEX IF NOT EXISTS idx_fact_events_goal ON fact_events(goal_id);
                CREATE INDEX IF NOT EXISTS idx_fact_events_importance ON fact_events(importance_score DESC);
                CREATE INDEX IF NOT EXISTS idx_fact_events_retention ON fact_events(retention_class);

                CREATE TABLE IF NOT EXISTS runtime_observations (
                    event_id TEXT PRIMARY KEY,
                    correlation_id TEXT NOT NULL,
                    parent_event_id TEXT,
                    timestamp REAL NOT NULL,
                    created_at REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_item_id TEXT,
                    memory_domain INTEGER NOT NULL,
                    ingest_target INTEGER NOT NULL,
                    cognition_eligible INTEGER NOT NULL DEFAULT 0,
                    tom_depth INTEGER NOT NULL DEFAULT 1,
                    retention_class INTEGER NOT NULL DEFAULT 2,
                    session_id TEXT,
                    user_id TEXT,
                    task_id TEXT,
                    goal_id TEXT,
                    raw_content TEXT NOT NULL,
                    structured_payload TEXT,
                    metadata TEXT,
                    importance_score REAL NOT NULL DEFAULT 0.5,
                    importance_t0_base REAL,
                    importance_t1_score REAL,
                    importance_version INTEGER NOT NULL DEFAULT 1,
                    level INTEGER NOT NULL DEFAULT 1,
                    media_path TEXT,
                    deleted_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_runtime_observations_timestamp ON runtime_observations(timestamp);
                CREATE INDEX IF NOT EXISTS idx_runtime_observations_type ON runtime_observations(event_type);
                CREATE INDEX IF NOT EXISTS idx_runtime_observations_source ON runtime_observations(source);
                CREATE INDEX IF NOT EXISTS idx_runtime_observations_domain ON runtime_observations(memory_domain);
                CREATE INDEX IF NOT EXISTS idx_runtime_observations_session ON runtime_observations(session_id);
                CREATE INDEX IF NOT EXISTS idx_runtime_observations_user ON runtime_observations(user_id);
                CREATE INDEX IF NOT EXISTS idx_runtime_observations_goal ON runtime_observations(goal_id);
                CREATE INDEX IF NOT EXISTS idx_runtime_observations_importance ON runtime_observations(importance_score DESC);
                CREATE INDEX IF NOT EXISTS idx_runtime_observations_retention ON runtime_observations(retention_class);

                CREATE TABLE IF NOT EXISTS l1_event_vectors (
                    vec_rowid INTEGER PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding_dim INTEGER NOT NULL,
                    vec_table TEXT NOT NULL,
                    metadata TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(event_id, embedding_model)
                );
                CREATE INDEX IF NOT EXISTS idx_l1_event_vectors_event ON l1_event_vectors(event_id);
                CREATE INDEX IF NOT EXISTS idx_l1_event_vectors_model ON l1_event_vectors(embedding_model);

                CREATE VIRTUAL TABLE IF NOT EXISTS l1_events_fts USING fts5(
                    event_id UNINDEXED,
                    raw_content,
                    tokenize='unicode61'
                );
                """
            )
            if self._vector_enabled:
                await self._vector_index.initialize()
            await db.commit()

        if self._embedding_queue is not None and self._embedding_worker is None:
            self._embedding_worker = asyncio.create_task(self._run_embedding_worker())
        self._initialized = True

    async def shutdown(self) -> None:
        if self._embedding_queue is not None and self._embedding_worker is not None:
            await self._embedding_queue.put(None)
            await self._embedding_worker
            self._embedding_worker = None
        if self._vector_index is not None:
            await self._vector_index.close()

    async def store(self, event: MemoryEvent) -> str:
        """Persist a normalized memory event."""
        await self.initialize()
        table_name = self._resolve_target_table(event)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"""
                INSERT OR REPLACE INTO {table_name}(
                    event_id, correlation_id, parent_event_id, timestamp, created_at,
                    event_type, source, source_item_id, memory_domain, ingest_target,
                    cognition_eligible, tom_depth, retention_class, session_id, user_id,
                    task_id, goal_id, raw_content, structured_payload, metadata,
                    importance_score, importance_t0_base, importance_t1_score, importance_version,
                    level, media_path, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.correlation_id,
                    event.parent_event_id,
                    float(event.timestamp),
                    float(event.created_at),
                    event.event_type,
                    event.source,
                    event.source_item_id,
                    int(event.memory_domain),
                    int(event.ingest_target),
                    1 if event.cognition_eligible else 0,
                    int(event.tom_depth),
                    int(event.retention_class),
                    event.session_id,
                    event.user_id,
                    event.task_id,
                    event.goal_id,
                    event.raw_content,
                    event.structured_payload,
                    event.metadata,
                    float(event.importance_score),
                    float(event.importance_t0_base),
                    event.importance_t1_score,
                    int(event.importance_version),
                    int(event.level),
                    event.media_path,
                    None,
                ),
            )
            # Sync FTS5 index
            tokenized = tokenize_for_fts(event.raw_content)
            await db.execute(
                "DELETE FROM l1_events_fts WHERE event_id = ?",
                (event.event_id,),
            )
            await db.execute(
                "INSERT INTO l1_events_fts(event_id, raw_content) VALUES (?, ?)",
                (event.event_id, tokenized),
            )
            await db.commit()
        await self._schedule_event_embedding(event)
        return event.event_id

    async def search_events(
        self,
        *,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        event_type: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        domain_filters: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search L1 events using sqlite-vec and fall back to keyword matching."""
        semantic_hits = await self._semantic_search_event_hits(query=query, limit=max(limit * 5, 20))
        if semantic_hits:
            return await self._fetch_ranked_events(
                hits=semantic_hits,
                session_id=session_id,
                user_id=user_id,
                event_type=event_type,
                source_filters=source_filters,
                domain_filters=domain_filters,
                limit=limit,
            )

        events = await self.query_events(
            session_id=session_id,
            user_id=user_id,
            event_type=event_type,
            source_filters=source_filters,
            limit=max(limit * 5, 20),
        )
        allowed_domains = {MemoryDomain.from_value(value).label for value in domain_filters or []}
        query_tokens = [token for token in query.lower().split() if token]
        filtered = [
            event
            for event in events
            if event["memory_domain"] != MemoryDomain.RUNTIME_TELEMETRY.label
            and (not allowed_domains or event["memory_domain"] in allowed_domains)
            and all(token in event["raw_content"].lower() for token in query_tokens)
        ]
        return filtered[:limit]

    async def store_timeline_event(self, event: TimelineEvent) -> str:
        """Normalize a timeline event into the L1 schema."""
        timeline_payload = event.to_dict()
        runtime_event = Event(
            type="TIMELINE_EVENT",
            data={
                "title": event.title,
                "summary": event.summary,
                "content_blocks": timeline_payload["content_blocks"],
                "entities": event.entities,
                "tags": event.tags,
            },
            timestamp=event.occurred_at,
            source=event.source_type,
            level=EventLevel.INFO,
            correlation_id=event.event_id,
            metadata={
                "timeline": timeline_payload,
                "processing_status": event.processing_status,
                "raw_payload_ref": event.raw_payload_ref,
            },
        )
        memory_event = normalize_runtime_event(runtime_event, event_id=event.event_id)
        return await self.store(memory_event)

    async def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single event by id."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE event_id = ?",
                (event_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def get_memory_event(self, event_id: str) -> Optional[MemoryEvent]:
        """Fetch a single event as the canonical MemoryEvent contract."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE event_id = ?",
                (event_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self._row_to_memory_event(row) if row else None

    async def list_events(self, *, limit: int = 100, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List the newest events, optionally constrained by event type."""
        return await self.query_events(event_type=event_type, limit=limit)

    async def query_events(
        self,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        memory_domain: Optional[str] = None,
        event_type: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        cognition_eligible: Optional[bool] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query events with SQL-level filters."""
        await self.initialize()
        query = f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE deleted_at IS NULL"
        args: List[Any] = []

        if session_id:
            query += " AND session_id = ?"
            args.append(session_id)
        if user_id:
            query += " AND user_id = ?"
            args.append(user_id)
        if memory_domain:
            query += " AND memory_domain = ?"
            args.append(int(MemoryDomain.from_value(memory_domain)))
        if event_type:
            query += " AND event_type = ?"
            args.append(event_type)
        if source_filters:
            placeholders = ", ".join("?" for _ in source_filters)
            query += f" AND source IN ({placeholders})"
            args.extend(source_filters)
        if cognition_eligible is not None:
            query += " AND cognition_eligible = ?"
            args.append(1 if cognition_eligible else 0)
        if start_time is not None:
            query += " AND timestamp >= ?"
            args.append(float(start_time))
        if end_time is not None:
            query += " AND timestamp <= ?"
            args.append(float(end_time))

        query += " ORDER BY timestamp DESC LIMIT ?"
        args.append(int(limit))

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def get_timeline_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Return the original timeline payload for a timeline event."""
        payload = await self.get_event(event_id)
        if payload is None:
            return None
        timeline = payload.get("metadata", {}).get("timeline")
        return timeline if isinstance(timeline, dict) else None

    async def list_timeline_events(self, *, limit: int = 100, source_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List timeline events with optional source filtering."""
        events = await self.query_events(event_type="TIMELINE_EVENT", limit=limit)
        items: List[Dict[str, Any]] = []
        for event in events:
            timeline = event.get("metadata", {}).get("timeline")
            if not isinstance(timeline, dict):
                continue
            if source_type and timeline.get("source_type") != source_type:
                continue
            items.append(timeline)
        return items

    async def count_events(self) -> int:
        """Count all non-deleted events."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                f"SELECT COUNT(*) FROM {FACT_EVENTS_TABLE} WHERE deleted_at IS NULL"
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def count_runtime_observations(self) -> int:
        """Count all non-deleted runtime observations."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                f"SELECT COUNT(*) FROM {RUNTIME_OBSERVATIONS_TABLE} WHERE deleted_at IS NULL"
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def clear(self) -> int:
        """Delete all events and return the removed count."""
        count = await self.count_events()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(f"DELETE FROM {FACT_EVENTS_TABLE}")
            await db.execute("DELETE FROM l1_events_fts")
            await db.commit()
        if self._vector_index is not None:
            await self._vector_index.clear()
        return count

    async def clear_runtime_observations(self) -> int:
        """Delete all runtime observations and return the removed count."""
        count = await self.count_runtime_observations()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(f"DELETE FROM {RUNTIME_OBSERVATIONS_TABLE}")
            await db.commit()
        return count

    async def mark_deleted(self, event_id: str, *, deleted_at: Optional[float] = None) -> bool:
        """Soft-delete an event."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                f"UPDATE {FACT_EVENTS_TABLE} SET deleted_at = ? WHERE event_id = ?",
                (float(deleted_at or time.time()), event_id),
            )
            await db.execute(
                "DELETE FROM l1_events_fts WHERE event_id = ?",
                (event_id,),
            )
            await db.commit()
        if cursor.rowcount > 0 and self._vector_index is not None:
            await self._vector_index.delete_entity(entity_id=event_id)
        return cursor.rowcount > 0

    async def query_runtime_observations(
        self,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        event_type: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query runtime observations with SQL-level filters."""
        await self.initialize()
        query = f"SELECT * FROM {RUNTIME_OBSERVATIONS_TABLE} WHERE deleted_at IS NULL"
        args: List[Any] = []

        if session_id:
            query += " AND session_id = ?"
            args.append(session_id)
        if user_id:
            query += " AND user_id = ?"
            args.append(user_id)
        if event_type:
            query += " AND event_type = ?"
            args.append(event_type)
        if start_time is not None:
            query += " AND timestamp >= ?"
            args.append(float(start_time))
        if end_time is not None:
            query += " AND timestamp <= ?"
            args.append(float(end_time))

        query += " ORDER BY timestamp DESC LIMIT ?"
        args.append(int(limit))

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def bm25_search(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> List[Tuple[str, float]]:
        """Search L1 events via FTS5 BM25 ranking.

        Returns a list of (event_id, bm25_score) tuples ordered by relevance.
        Lower bm25 scores indicate higher relevance in SQLite FTS5.
        """
        await self.initialize()
        tokenized = tokenize_for_fts(query)
        if not tokenized:
            return []
        escaped = escape_fts_query(tokenized)
        if not escaped:
            return []
        async with aiosqlite.connect(self.db_path) as db:
            try:
                async with db.execute(
                    """
                    SELECT event_id, bm25(l1_events_fts) AS score
                    FROM l1_events_fts
                    WHERE l1_events_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (escaped, limit),
                ) as cursor:
                    rows = await cursor.fetchall()
                return [(str(row[0]), float(row[1])) for row in rows]
            except Exception as exc:
                logger.warning("FTS5 BM25 search failed: %s", exc)
                return []

    async def backfill_fts(self, *, batch_size: int = 500) -> int:
        """Backfill the FTS5 index from existing fact_events rows.

        Returns the number of rows indexed.
        """
        await self.initialize()
        indexed = 0
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                f"""
                SELECT event_id, raw_content FROM {FACT_EVENTS_TABLE}
                WHERE deleted_at IS NULL
                AND event_id NOT IN (SELECT event_id FROM l1_events_fts)
                """
            ) as cursor:
                batch: list[tuple[str, str]] = []
                async for row in cursor:
                    event_id = str(row[0])
                    raw = str(row[1])
                    batch.append((event_id, tokenize_for_fts(raw)))
                    if len(batch) >= batch_size:
                        await db.executemany(
                            "INSERT INTO l1_events_fts(event_id, raw_content) VALUES (?, ?)",
                            batch,
                        )
                        indexed += len(batch)
                        batch.clear()
                if batch:
                    await db.executemany(
                        "INSERT INTO l1_events_fts(event_id, raw_content) VALUES (?, ?)",
                        batch,
                    )
                    indexed += len(batch)
            await db.commit()
        return indexed

    def _resolve_target_table(self, event: MemoryEvent) -> str:
        event_type = str(event.event_type)
        if event_type in RUNTIME_OBSERVATION_EVENT_TYPES:
            return RUNTIME_OBSERVATIONS_TABLE
        if event.memory_domain in {MemoryDomain.RUNTIME_TELEMETRY, MemoryDomain.SYSTEM_CONTROL, MemoryDomain.INTERACTION}:
            return RUNTIME_OBSERVATIONS_TABLE
        return FACT_EVENTS_TABLE

    async def _maybe_upsert_event_embedding(self, event: MemoryEvent) -> None:
        if not self._vector_enabled or self._embedding_service is None or self._vector_index is None:
            return
        if event.memory_domain in {MemoryDomain.RUNTIME_TELEMETRY, MemoryDomain.SYSTEM_CONTROL}:
            return
        embedding = await self._embedding_service.embed_text(event.raw_content)
        if embedding is None:
            return
        try:
            await self._vector_index.upsert(
                entity_id=event.event_id,
                embedding=embedding,
                metadata={"event_type": event.event_type, "source": event.source},
            )
        except Exception as exc:
            logger.warning("Failed to upsert event embedding for %s: %s", event.event_id, exc)

    async def _semantic_search_event_hits(self, *, query: str, limit: int) -> list[VectorSearchHit]:
        if not self._vector_enabled or self._embedding_service is None or self._vector_index is None or not query.strip():
            return []
        embedding = await self._embedding_service.embed_text(query)
        if embedding is None:
            return []
        try:
            return await self._vector_index.search(embedding=embedding, limit=limit)
        except Exception as exc:
            logger.warning("Failed semantic search over L1 events: %s", exc)
            return []

    async def _schedule_event_embedding(self, event: MemoryEvent) -> None:
        if not self._vector_enabled:
            return
        if self._embedding_queue is not None:
            await self._embedding_queue.put(event)
            return
        await self._maybe_upsert_event_embedding(event)

    async def _run_embedding_worker(self) -> None:
        if self._embedding_queue is None:
            return
        while True:
            item = await self._embedding_queue.get()
            if item is None:
                self._embedding_queue.task_done()
                break
            try:
                await self._maybe_upsert_event_embedding(item)
            finally:
                self._embedding_queue.task_done()

    async def _fetch_ranked_events(
        self,
        *,
        hits: list[VectorSearchHit],
        session_id: Optional[str],
        user_id: Optional[str],
        event_type: Optional[str],
        source_filters: Optional[List[str]],
        domain_filters: Optional[List[str]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        if not hits:
            return []
        event_ids = [hit.entity_id for hit in hits]
        query = f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE deleted_at IS NULL"
        args: list[Any] = []
        placeholders = ", ".join("?" for _ in event_ids)
        query += f" AND event_id IN ({placeholders})"
        args.extend(event_ids)
        if session_id:
            query += " AND session_id = ?"
            args.append(session_id)
        if user_id:
            query += " AND user_id = ?"
            args.append(user_id)
        if event_type:
            query += " AND event_type = ?"
            args.append(event_type)
        if source_filters:
            source_placeholders = ", ".join("?" for _ in source_filters)
            query += f" AND source IN ({source_placeholders})"
            args.extend(source_filters)
        allowed_domains = [MemoryDomain.from_value(value) for value in domain_filters or []]
        if allowed_domains:
            domain_placeholders = ", ".join("?" for _ in allowed_domains)
            query += f" AND memory_domain IN ({domain_placeholders})"
            args.extend(int(domain) for domain in allowed_domains)
        else:
            query += " AND memory_domain != ?"
            args.append(int(MemoryDomain.RUNTIME_TELEMETRY))

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        events_by_id = {str(row["event_id"]): self._row_to_dict(row) for row in rows}
        ranked: list[Dict[str, Any]] = []
        for hit in hits:
            event = events_by_id.get(hit.entity_id)
            if event is None:
                continue
            event["distance"] = hit.distance
            ranked.append(event)
            if len(ranked) >= limit:
                break
        return ranked

    def _row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        return {
            "event_id": str(row["event_id"]),
            "correlation_id": str(row["correlation_id"]),
            "parent_event_id": row["parent_event_id"],
            "timestamp": float(row["timestamp"]),
            "created_at": float(row["created_at"]),
            "event_type": str(row["event_type"]),
            "source": str(row["source"]),
            "source_item_id": row["source_item_id"],
            "memory_domain": MemoryDomain.from_value(row["memory_domain"]).label,
            "ingest_target": IngestTarget.from_value(row["ingest_target"]).label,
            "cognition_eligible": bool(row["cognition_eligible"]),
            "tom_depth": TomDepth.from_value(row["tom_depth"]).label,
            "retention_class": RetentionClass.from_value(row["retention_class"]).label,
            "session_id": row["session_id"],
            "user_id": row["user_id"],
            "task_id": row["task_id"],
            "goal_id": row["goal_id"],
            "raw_content": str(row["raw_content"]),
            "structured_payload": json.loads(row["structured_payload"] or "{}"),
            "metadata": json.loads(row["metadata"] or "{}"),
            "importance_score": float(row["importance_score"]),
            "importance_t0_base": float(row["importance_t0_base"] or 0.0),
            "importance_t1_score": float(row["importance_t1_score"]) if row["importance_t1_score"] is not None else None,
            "importance_version": int(row["importance_version"]),
            "level": int(row["level"]),
            "media_path": row["media_path"],
            "deleted_at": float(row["deleted_at"]) if row["deleted_at"] is not None else None,
        }

    def _row_to_memory_event(self, row: aiosqlite.Row) -> MemoryEvent:
        structured_payload = json.loads(row["structured_payload"] or "{}")
        metadata = json.loads(row["metadata"] or "{}")
        entity_focus_hint = None
        if isinstance(structured_payload, dict):
            entity_focus_hint = structured_payload.get("entity_focus_hint")
        if not entity_focus_hint and isinstance(metadata, dict):
            entity_focus_hint = metadata.get("entity_focus_hint")
        derived_from_event_ids: list[str] = []
        if isinstance(metadata, dict):
            raw_derived = metadata.get("derived_from_event_ids")
            if isinstance(raw_derived, list):
                derived_from_event_ids = [text for item in raw_derived if (text := str(item).strip())]

        return MemoryEvent(
            event_id=str(row["event_id"]),
            correlation_id=str(row["correlation_id"]),
            parent_event_id=row["parent_event_id"],
            timestamp=float(row["timestamp"]),
            created_at=float(row["created_at"]),
            event_type=str(row["event_type"]),
            source=str(row["source"]),
            source_item_id=row["source_item_id"],
            memory_domain=MemoryDomain.from_value(row["memory_domain"]),
            ingest_target=IngestTarget.from_value(row["ingest_target"]),
            cognition_eligible=bool(row["cognition_eligible"]),
            tom_depth=TomDepth.from_value(row["tom_depth"]),
            retention_class=RetentionClass.from_value(row["retention_class"]),
            session_id=row["session_id"],
            user_id=row["user_id"],
            task_id=row["task_id"],
            goal_id=row["goal_id"],
            raw_content=str(row["raw_content"]),
            structured_payload=json.dumps(structured_payload, ensure_ascii=False),
            metadata=json.dumps(metadata, ensure_ascii=False),
            importance_score=float(row["importance_score"]),
            importance_t0_base=float(row["importance_t0_base"] or 0.0),
            importance_t1_score=float(row["importance_t1_score"]) if row["importance_t1_score"] is not None else None,
            importance_version=int(row["importance_version"]),
            level=int(row["level"]),
            media_path=row["media_path"],
            entity_focus_hint=str(entity_focus_hint).strip() if entity_focus_hint else None,
            speaker_role=str(metadata.get("speaker_role")).strip() if isinstance(metadata, dict) and metadata.get("speaker_role") else None,
            grounding_type=str(metadata.get("grounding_type")).strip() if isinstance(metadata, dict) and metadata.get("grounding_type") else None,
            derived_from_event_ids=derived_from_event_ids,
            semantic_owner_hint=str(metadata.get("semantic_owner_hint")).strip() if isinstance(metadata, dict) and metadata.get("semantic_owner_hint") else None,
            originality_type=str(metadata.get("originality_type")).strip() if isinstance(metadata, dict) and metadata.get("originality_type") else None,
        )


__all__ = ["L1EventStore"]
