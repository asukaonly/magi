"""Canonical L1 event store for normalized memory events."""

from __future__ import annotations

import logging
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ...config.models import EmbeddingBackend
from ...events.events import Event, EventLevel, EventTypes
from ..embedding.chunking import ChunkedText, chunk_sentences, chunk_text
from ..embedding.embedding_pipeline import EmbeddingPipelineItem, MemoryEmbeddingPipeline
from ..embedding.embedding_service import EmbeddingProfile, MemoryEmbeddingService
from ..embedding.embedding_text_builders import build_l1_embedding_text
from ..event_contracts import IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth, normalize_runtime_event
from ..hybrid_retrieval.fts_utils import build_exact_fts_query, build_or_fts_query, build_stemmed_fts_query, escape_fts_query, tokenize_for_fts
from .chat_sessions import ensure_chat_sessions_schema_async, project_chat_event_to_session
from ..embedding.sqlite_vec_index import SqliteVecIndex, VectorSearchHit

FACT_EVENTS_TABLE = "fact_events"
EMBEDDING_PROFILES_TABLE = "embedding_profiles"
EVENT_CHUNKS_TABLE = "l1_event_chunks"
EMBEDDING_TEXT_BUILDER_VERSION = "l1_content_v1"
EMBEDDING_STATUS_PENDING = "pending"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_FAILED = "failed"
EMBEDDING_STATUS_SKIPPED = "skipped"
EMBEDDING_STATUS_DISABLED = "disabled"
EMBEDDING_STATUS_STALE = "stale"
EMBEDDING_QUEUE_MAXSIZE = 512
DEFAULT_EMBEDDING_WORKER_COUNT = 2

logger = logging.getLogger(__name__)

L1_STORE_DIAGNOSTIC_EVENT_TYPES = {
    EventTypes.USER_MESSAGE,
    EventTypes.AI_RESPONSE,
    EventTypes.ACTION_EXECUTED,
}


class L1EventStore:
    """Stores immutable normalized memory events in SQLite."""

    def __init__(
        self,
        *,
        db_path: str = "~/.magi/data/memory/l1_events.db",
        embedding_service: MemoryEmbeddingService | None = None,
        memory_config_getter: Callable[[], Any] | None = None,
        vector_enabled: bool = True,
        async_embeddings: bool = True,
        embedding_worker_count: int = DEFAULT_EMBEDDING_WORKER_COUNT,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._embedding_service = embedding_service
        self._memory_config_getter = memory_config_getter
        self._default_vector_enabled = bool(vector_enabled and embedding_service is not None)
        self._default_async_embeddings = bool(async_embeddings)
        self._embedding_worker_count = max(1, int(embedding_worker_count))
        self._vector_index = (
            SqliteVecIndex(
                db_path=self.db_path,
                registry_table="l1_event_chunk_vectors",
                entity_column="chunk_id",
                vec_table_prefix="l1_event_vec",
                partition_key_column="user_id",
            )
            if embedding_service is not None or vector_enabled
            else None
        )
        self._embedding_queue: asyncio.Queue[MemoryEvent | None] | None = (
            asyncio.Queue(maxsize=max(EMBEDDING_QUEUE_MAXSIZE, self._embedding_worker_count))
            if embedding_service is not None
            else None
        )
        self._embedding_workers: list[asyncio.Task[None]] = []
        self._embedding_batch_size = 5
        self._embedding_batch_wait_seconds = 1.0
        self._initialized = False

    async def initialize(self) -> None:
        """Create the canonical L1 schema."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS fact_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    correlation_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    created_at REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_item_id TEXT,
                    idempotency_key TEXT,
                    memory_domain INTEGER NOT NULL,
                    ingest_target INTEGER NOT NULL,
                    cognition_eligible INTEGER NOT NULL DEFAULT 0,
                    tom_depth INTEGER NOT NULL DEFAULT 1,
                    retention_class INTEGER NOT NULL DEFAULT 2,
                    session_id TEXT,
                    turn_id TEXT,
                    user_id TEXT,
                    task_id TEXT,
                    content TEXT NOT NULL,
                    author_type TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    importance_score REAL NOT NULL DEFAULT 0.5,
                    level INTEGER NOT NULL DEFAULT 1,
                    media_path TEXT,
                    metadata_json TEXT,
                    embedding_status TEXT NOT NULL DEFAULT 'disabled',
                    embedding_profile_id TEXT,
                    embedding_chunk_count INTEGER NOT NULL DEFAULT 0,
                    last_embedded_at REAL,
                    deleted_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_fact_events_timestamp ON fact_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_fact_events_type ON fact_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_fact_events_source ON fact_events(source);
                CREATE INDEX IF NOT EXISTS idx_fact_events_idempotency_key ON fact_events(idempotency_key);
                CREATE INDEX IF NOT EXISTS idx_fact_events_domain ON fact_events(memory_domain);
                CREATE INDEX IF NOT EXISTS idx_fact_events_session ON fact_events(session_id);
                CREATE INDEX IF NOT EXISTS idx_fact_events_turn ON fact_events(turn_id);
                CREATE INDEX IF NOT EXISTS idx_fact_events_user ON fact_events(user_id);
                CREATE INDEX IF NOT EXISTS idx_fact_events_importance ON fact_events(importance_score DESC);
                CREATE INDEX IF NOT EXISTS idx_fact_events_retention ON fact_events(retention_class);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_fact_events_business_idempotency
                    ON fact_events(source, event_type, idempotency_key);
                CREATE TABLE IF NOT EXISTS embedding_profiles (
                    profile_id TEXT PRIMARY KEY,
                    provider_name TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    embedding_dim INTEGER,
                    text_builder_version TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS l1_event_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL,
                    char_start INTEGER NOT NULL,
                    char_end INTEGER NOT NULL,
                    token_estimate INTEGER NOT NULL,
                    embedding_profile_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_l1_event_chunks_event ON l1_event_chunks(event_id, chunk_index);

                CREATE VIRTUAL TABLE IF NOT EXISTS l1_events_fts USING fts5(
                    event_id UNINDEXED,
                    content,
                    tokenize='unicode61'
                );
                """
            )
            # l1_event_entities for entity co-occurrence expansion (separate
            # from executescript to avoid FTS5 virtual-table edge cases).
            await db.execute(
                """CREATE TABLE IF NOT EXISTS l1_event_entities (
                    event_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    entity_type TEXT,
                    confidence REAL,
                    created_at REAL NOT NULL,
                    UNIQUE(event_id, entity_id)
                )"""
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_l1_event_entities_event"
                " ON l1_event_entities(event_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_l1_event_entities_entity"
                " ON l1_event_entities(entity_id)"
            )
            await self._ensure_event_identity_schema(db)
            await self._ensure_embedding_status_columns(db)
            await self._ensure_metadata_json_column(db)
            await db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_fact_events_embedding_status ON {FACT_EVENTS_TABLE}(embedding_status)"
            )
            await db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_fact_events_embedding_profile ON {FACT_EVENTS_TABLE}(embedding_profile_id)"
            )
            await ensure_chat_sessions_schema_async(db)
            if self._vector_index is not None:
                await self._vector_index.initialize()
            await db.commit()

        if self._embedding_queue is not None and not self._embedding_workers:
            self._embedding_workers = [
                asyncio.create_task(self._run_embedding_worker())
                for _ in range(self._embedding_worker_count)
            ]
        self._initialized = True

    async def shutdown(self) -> None:
        if self._embedding_queue is not None and self._embedding_workers:
            for _ in self._embedding_workers:
                await self._embedding_queue.put(None)
            await asyncio.gather(*self._embedding_workers)
            self._embedding_workers = []
        if self._vector_index is not None:
            await self._vector_index.close()

    def _current_memory_config(self) -> Any | None:
        if self._memory_config_getter is None:
            return None
        try:
            return self._memory_config_getter()
        except Exception as exc:
            logger.debug("Failed to resolve current memory config: %s", exc)
            return None

    def _vectors_enabled(self) -> bool:
        if self._embedding_service is None:
            return False
        config = self._current_memory_config()
        if config is None:
            return self._default_vector_enabled
        return bool(
            config.embedding.backend == EmbeddingBackend.SQLITE_VEC
            and config.l1.enabled
            and config.l1.vectors_enabled
        )

    def _async_embeddings_enabled(self) -> bool:
        config = self._current_memory_config()
        if config is None:
            return self._default_async_embeddings
        return bool(config.async_embeddings)

    def _resolve_active_embedding_profile_id(self) -> tuple[str | None, dict[str, Any]]:
        started_at = time.perf_counter()
        if self._embedding_service is None:
            finished_at = time.perf_counter()
            return None, {
                "lookup_ms": round((finished_at - started_at) * 1000.0, 2),
                "config_ms": 0.0,
                "decision_ms": 0.0,
                "profile_ms": 0.0,
                "vectors_enabled": False,
                "used_default_vector_setting": False,
                "reason": "embedding_service_missing",
            }

        config = self._current_memory_config()
        config_resolved_at = time.perf_counter()
        if config is None:
            vectors_enabled = self._default_vector_enabled
            used_default_vector_setting = True
        else:
            vectors_enabled = bool(
                config.embedding.backend == EmbeddingBackend.SQLITE_VEC
                and config.l1.enabled
                and config.l1.vectors_enabled
            )
            used_default_vector_setting = False
        vectors_decided_at = time.perf_counter()

        getter = getattr(self._embedding_service, "get_active_profile", None)
        if not vectors_enabled:
            finished_at = time.perf_counter()
            return None, {
                "lookup_ms": round((finished_at - started_at) * 1000.0, 2),
                "config_ms": round((config_resolved_at - started_at) * 1000.0, 2),
                "decision_ms": round((vectors_decided_at - config_resolved_at) * 1000.0, 2),
                "profile_ms": 0.0,
                "vectors_enabled": False,
                "used_default_vector_setting": used_default_vector_setting,
                "reason": "vectors_disabled",
            }
        if not callable(getter):
            finished_at = time.perf_counter()
            return None, {
                "lookup_ms": round((finished_at - started_at) * 1000.0, 2),
                "config_ms": round((config_resolved_at - started_at) * 1000.0, 2),
                "decision_ms": round((vectors_decided_at - config_resolved_at) * 1000.0, 2),
                "profile_ms": 0.0,
                "vectors_enabled": True,
                "used_default_vector_setting": used_default_vector_setting,
                "reason": "profile_getter_missing",
            }

        profile = getter(text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION)
        finished_at = time.perf_counter()
        return (
            profile.profile_id if profile is not None else None,
            {
                "lookup_ms": round((finished_at - started_at) * 1000.0, 2),
                "config_ms": round((config_resolved_at - started_at) * 1000.0, 2),
                "decision_ms": round((vectors_decided_at - config_resolved_at) * 1000.0, 2),
                "profile_ms": round((finished_at - vectors_decided_at) * 1000.0, 2),
                "vectors_enabled": True,
                "used_default_vector_setting": used_default_vector_setting,
                "reason": "resolved" if profile is not None else "profile_missing",
            },
        )

    async def store(self, event: MemoryEvent) -> str:
        """Persist a normalized memory event."""
        await self.initialize()
        if event.source == "calendar":
            logger.info(
                "L1EventStore storing calendar event | "
                "event_id=%s event_type=%s source_item_id=%s content=%s metadata_json=%s",
                event.event_id,
                event.event_type,
                event.source_item_id,
                event.content,
                event.metadata_json,
            )
        if event.event_type in L1_STORE_DIAGNOSTIC_EVENT_TYPES:
            logger.info(
                "L1EventStore persisting event | event_id=%s type=%s session_id=%s user_id=%s correlation_id=%s",
                event.event_id,
                event.event_type,
                event.session_id,
                event.user_id,
                event.correlation_id,
            )
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            cursor = await db.execute(
                f"""
                INSERT OR IGNORE INTO {FACT_EVENTS_TABLE}(
                    event_id, correlation_id, timestamp, created_at,
                    event_type, source, source_item_id, idempotency_key, memory_domain, ingest_target,
                    cognition_eligible, tom_depth, retention_class, session_id, turn_id, user_id,
                    task_id, content, author_type, content_type, importance_score,
                    level, media_path, metadata_json, embedding_status, embedding_profile_id,
                    embedding_chunk_count, last_embedded_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.correlation_id,
                    float(event.timestamp),
                    float(event.created_at),
                    event.event_type,
                    event.source,
                    event.source_item_id,
                    event.idempotency_key,
                    int(event.memory_domain),
                    int(event.ingest_target),
                    1 if event.cognition_eligible else 0,
                    int(event.tom_depth),
                    int(event.retention_class),
                    event.session_id,
                    event.turn_id,
                    event.user_id,
                    event.task_id,
                    event.content,
                    event.author_type,
                    event.content_type,
                    float(event.importance_score),
                    int(event.level),
                    event.media_path,
                    json.dumps(event.metadata_json) if event.metadata_json is not None else None,
                    self._initial_embedding_status(event),
                    self._initial_embedding_profile_id(event),
                    0,
                    None,
                    None,
                ),
            )
            inserted = cursor.rowcount > 0
            if not inserted:
                await db.rollback()
                existing_event_id = await self._resolve_existing_event_id(db, event)
                if event.event_type in L1_STORE_DIAGNOSTIC_EVENT_TYPES:
                    logger.info(
                        "L1EventStore skipped duplicate event | event_id=%s type=%s",
                        event.event_id,
                        event.event_type,
                    )
                return existing_event_id or event.event_id
            # Sync FTS5 index
            tokenized = tokenize_for_fts(self.get_search_text(event))
            await db.execute(
                "DELETE FROM l1_events_fts WHERE event_id = ?",
                (event.event_id,),
            )
            await db.execute(
                "INSERT INTO l1_events_fts(event_id, content) VALUES (?, ?)",
                (event.event_id, tokenized),
            )
            await project_chat_event_to_session(
                db,
                user_id=event.user_id,
                session_id=event.session_id,
                event_type=event.event_type,
                content=event.content,
                timestamp=float(event.timestamp),
            )
            await db.commit()
        if event.event_type in L1_STORE_DIAGNOSTIC_EVENT_TYPES:
            logger.info(
                "L1EventStore persisted event | event_id=%s type=%s",
                event.event_id,
                event.event_type,
            )
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
            ranked_events = await self._fetch_ranked_events(
                hits=semantic_hits,
                session_id=session_id,
                user_id=user_id,
                event_type=event_type,
                source_filters=source_filters,
                domain_filters=domain_filters,
                limit=limit,
            )
            if ranked_events:
                return ranked_events

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
            and all(token in event["content"].lower() for token in query_tokens)
        ]
        return filtered[:limit]

    async def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single event by id."""
        await self.initialize()
        try:
            active_embedding_profile_id, _ = self._resolve_active_embedding_profile_id()
        except Exception:
            active_embedding_profile_id = None
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE event_id = ?",
                (event_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return (
            self._row_to_dict(row, active_embedding_profile_id=active_embedding_profile_id)
            if row
            else None
        )

    async def get_memory_event(self, event_id: str) -> Optional[MemoryEvent]:
        """Fetch a single event as the canonical MemoryEvent contract."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE event_id = ?",
                (event_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self._row_to_memory_event(row) if row else None

    async def get_event_vectors(
        self,
        event_ids: List[str],
    ) -> Dict[str, List[float]]:
        """Return embedding vectors for the given event IDs.

        For each event, returns the chunk-0 embedding (primary chunk).
        Events without embeddings are silently omitted.
        """
        if not event_ids or self._vector_index is None:
            return {}
        chunk_ids = [self._chunk_id_for_event(eid, 0) for eid in event_ids]
        raw = await self._vector_index.get_vectors(entity_ids=chunk_ids)
        result: Dict[str, List[float]] = {}
        for eid in event_ids:
            cid = self._chunk_id_for_event(eid, 0)
            if cid in raw:
                result[eid] = raw[cid]
        return result

    # ------------------------------------------------------------------
    # L1 Event–Entity linkage (for entity co-occurrence expansion)
    # ------------------------------------------------------------------

    async def write_event_entities(
        self,
        mappings: List[Tuple[str, str, Optional[str], Optional[float]]],
    ) -> int:
        """Persist (event_id, entity_id, entity_type, confidence) tuples.

        Duplicates are silently ignored via INSERT OR IGNORE.
        Returns the number of rows inserted.
        """
        if not mappings:
            return 0
        await self.initialize()
        now = time.time()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.executemany(
                "INSERT OR IGNORE INTO l1_event_entities"
                " (event_id, entity_id, entity_type, confidence, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                [(eid, entid, etype, conf, now) for eid, entid, etype, conf in mappings],
            )
            await db.commit()
            return db.total_changes

    async def get_entity_event_ids(
        self,
        entity_ids: List[str],
        *,
        limit_per_entity: int = 20,
    ) -> Dict[str, List[str]]:
        """Return event IDs associated with each entity.

        Returns ``{entity_id: [event_id, ...]}`` with the most recent
        events first (by created_at DESC), capped at *limit_per_entity*.
        """
        if not entity_ids:
            return {}
        await self.initialize()
        result: Dict[str, List[str]] = {eid: [] for eid in entity_ids}
        async with sqlite_connection_async(self.db_path) as db:
            for entity_id in entity_ids:
                async with db.execute(
                    "SELECT event_id FROM l1_event_entities"
                    " WHERE entity_id = ?"
                    " ORDER BY created_at DESC"
                    " LIMIT ?",
                    (entity_id, limit_per_entity),
                ) as cursor:
                    rows = await cursor.fetchall()
                result[entity_id] = [r[0] for r in rows]
        return result

    async def get_event_entity_ids(
        self,
        event_ids: List[str],
    ) -> Dict[str, List[str]]:
        """Return entity IDs for each event.

        Returns ``{event_id: [entity_id, ...]}`` for all given events.
        """
        if not event_ids:
            return {}
        await self.initialize()
        result: Dict[str, List[str]] = {eid: [] for eid in event_ids}
        async with sqlite_connection_async(self.db_path) as db:
            ph = ", ".join("?" for _ in event_ids)
            async with db.execute(
                f"SELECT event_id, entity_id FROM l1_event_entities WHERE event_id IN ({ph})",
                tuple(event_ids),
            ) as cursor:
                for row in await cursor.fetchall():
                    result.setdefault(row[0], []).append(row[1])
        return result

    async def expand_by_entities(
        self,
        seed_event_ids: List[str],
        *,
        limit: int = 30,
        exclude_event_ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Find events that share entities with *seed_event_ids*.

        Returns event IDs ordered by the number of shared entities (desc).
        """
        if not seed_event_ids:
            return []
        await self.initialize()
        exclude = set(exclude_event_ids or []) | set(seed_event_ids)

        async with sqlite_connection_async(self.db_path) as db:
            # Step 1: seed events → entity_ids
            ph = ", ".join("?" for _ in seed_event_ids)
            async with db.execute(
                f"SELECT DISTINCT entity_id FROM l1_event_entities WHERE event_id IN ({ph})",
                tuple(seed_event_ids),
            ) as cursor:
                entity_ids = [row[0] for row in await cursor.fetchall()]

            if not entity_ids:
                return []

            # Step 2: entity_ids → neighbouring event_ids (ranked by shared count)
            eph = ", ".join("?" for _ in entity_ids)
            async with db.execute(
                f"SELECT event_id, COUNT(DISTINCT entity_id) AS shared"
                f" FROM l1_event_entities"
                f" WHERE entity_id IN ({eph})"
                f" GROUP BY event_id"
                f" ORDER BY shared DESC"
                f" LIMIT ?",
                (*entity_ids, limit + len(exclude)),
            ) as cursor:
                rows = await cursor.fetchall()

        return [r[0] for r in rows if r[0] not in exclude][:limit]

    async def resolve_event_entities(self, event_ids: List[str]) -> List[str]:
        """Return distinct entity IDs linked to the given events."""
        if not event_ids:
            return []
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            ph = ", ".join("?" for _ in event_ids)
            async with db.execute(
                f"SELECT DISTINCT entity_id FROM l1_event_entities WHERE event_id IN ({ph})",
                tuple(event_ids),
            ) as cursor:
                return [row[0] for row in await cursor.fetchall()]

    async def find_events_by_entities(
        self,
        entity_ids: List[str],
        *,
        exclude_event_ids: Optional[List[str]] = None,
        limit: int = 30,
    ) -> List[Tuple[str, int]]:
        """Find events sharing given entities, ranked by shared-entity count.

        Returns ``[(event_id, shared_count), ...]`` ordered desc by *shared_count*.
        """
        if not entity_ids:
            return []
        await self.initialize()
        exclude = set(exclude_event_ids or [])
        eph = ", ".join("?" for _ in entity_ids)
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                f"SELECT event_id, COUNT(DISTINCT entity_id) AS shared"
                f" FROM l1_event_entities"
                f" WHERE entity_id IN ({eph})"
                f" GROUP BY event_id"
                f" ORDER BY shared DESC"
                f" LIMIT ?",
                (*entity_ids, limit + len(exclude)),
            ) as cursor:
                rows = await cursor.fetchall()
        return [(r[0], r[1]) for r in rows if r[0] not in exclude][:limit]

    async def filter_ids_by_user(self, event_ids: List[str], user_id: str) -> List[str]:
        """Return the subset of *event_ids* that belong to *user_id*."""
        if not event_ids:
            return []
        await self.initialize()
        ph = ", ".join("?" for _ in event_ids)
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                f"SELECT event_id FROM fact_events"
                f" WHERE event_id IN ({ph}) AND user_id = ? AND deleted_at IS NULL",
                (*event_ids, user_id),
            ) as cursor:
                rows = await cursor.fetchall()
        valid = {str(row[0]) for row in rows}
        return [eid for eid in event_ids if eid in valid]

    async def fetch_events(
        self,
        event_ids: List[str],
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        event_types: Optional[List[str]] = None,
        source_filters: Optional[List[str]] = None,
        domain_filters: Optional[List[str]] = None,
        exclude_domain: Optional[str] = None,
        time_start: Optional[float] = None,
        time_end: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Hydrate events by IDs with optional SQL filters, preserving input order.

        Parameters mirror the filtering logic used by hybrid retrieval handlers.
        *exclude_domain* defaults to ``RUNTIME_TELEMETRY`` when *domain_filters*
        is not provided.
        """
        if not event_ids:
            return []
        await self.initialize()

        sql = "SELECT * FROM fact_events WHERE deleted_at IS NULL"
        args: list[Any] = []
        ph = ", ".join("?" for _ in event_ids)
        sql += f" AND event_id IN ({ph})"
        args.extend(event_ids)

        if session_id:
            sql += " AND session_id = ?"
            args.append(session_id)
        if user_id:
            sql += " AND user_id = ?"
            args.append(user_id)
        if event_types:
            et_ph = ", ".join("?" for _ in event_types)
            sql += f" AND event_type IN ({et_ph})"
            args.extend(event_types)
        if source_filters:
            sf_ph = ", ".join("?" for _ in source_filters)
            sql += f" AND source IN ({sf_ph})"
            args.extend(source_filters)

        if domain_filters:
            domain_ints: list[int] = []
            for df in domain_filters:
                try:
                    domain_ints.append(int(MemoryDomain.from_value(df)))
                except (ValueError, KeyError):
                    pass
            if domain_ints:
                df_ph = ", ".join("?" for _ in domain_ints)
                sql += f" AND memory_domain IN ({df_ph})"
                args.extend(domain_ints)
        elif exclude_domain:
            try:
                sql += " AND memory_domain != ?"
                args.append(int(MemoryDomain.from_value(exclude_domain)))
            except (ValueError, KeyError):
                pass

        if time_start is not None:
            sql += " AND timestamp >= ?"
            args.append(time_start)
        if time_end is not None:
            sql += " AND timestamp <= ?"
            args.append(time_end)

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        events_by_id = {str(row["event_id"]): self._row_to_dict(row) for row in rows}
        return [events_by_id[eid] for eid in event_ids if eid in events_by_id]

    async def vector_search(
        self,
        *,
        query: str,
        limit: int = 100,
        user_id: Optional[str] = None,
    ) -> list[VectorSearchHit]:
        """Semantic vector search over L1 event chunks."""
        return await self._semantic_search_event_hits(
            query=query, limit=limit, user_id=user_id,
        )

    async def find_event_id_by_idempotency(
        self,
        *,
        source: str,
        event_type: str,
        idempotency_key: str | None,
    ) -> Optional[str]:
        """Find an existing event id by business idempotency tuple."""
        normalized_key = str(idempotency_key or "").strip()
        if not normalized_key:
            return None
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            return await self._find_event_id_by_idempotency(
                db,
                source=source,
                event_type=event_type,
                idempotency_key=normalized_key,
            )

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
        query: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        source_item_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        cognition_eligible: Optional[bool] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
        include_metadata_json: bool = True,
        include_embedding_fields: bool = True,
    ) -> List[Dict[str, Any]]:
        """Query events with SQL-level filters."""
        await self.initialize()
        sql = f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE deleted_at IS NULL"
        args: List[Any] = []

        if session_id:
            sql += " AND session_id = ?"
            args.append(session_id)
        if user_id:
            sql += " AND user_id = ?"
            args.append(user_id)
        if memory_domain:
            sql += " AND memory_domain = ?"
            args.append(int(MemoryDomain.from_value(memory_domain)))
        if event_type:
            sql += " AND event_type = ?"
            args.append(event_type)
        if query:
            sql += " AND LOWER(content) LIKE ?"
            args.append(f"%{str(query).strip().lower()}%")
        if source_filters:
            placeholders = ", ".join("?" for _ in source_filters)
            sql += f" AND source IN ({placeholders})"
            args.extend(source_filters)
        if source_item_id:
            sql += " AND source_item_id = ?"
            args.append(source_item_id)
        if idempotency_key:
            sql += " AND idempotency_key = ?"
            args.append(idempotency_key)
        if cognition_eligible is not None:
            sql += " AND cognition_eligible = ?"
            args.append(1 if cognition_eligible else 0)
        if start_time is not None:
            sql += " AND timestamp >= ?"
            args.append(float(start_time))
        if end_time is not None:
            sql += " AND timestamp <= ?"
            args.append(float(end_time))

        sql += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        args.append(int(limit))
        args.append(int(offset))

        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        if include_embedding_fields:
            active_embedding_profile_id, _ = self._resolve_active_embedding_profile_id()
        else:
            active_embedding_profile_id = None
        items = [
            self._row_to_dict(
                row,
                include_metadata_json=include_metadata_json,
                include_embedding_fields=include_embedding_fields,
                active_embedding_profile_id=active_embedding_profile_id,
            )
            for row in rows
        ]
        return items

    async def get_timeline_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Return a minimal timeline-shaped view from canonical L1 columns."""
        event = await self.get_event(event_id)
        return self._to_timeline_view(event)

    async def list_timeline_events(self, *, limit: int = 100, source_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List timeline-shaped views with optional source filtering."""
        events = await self.query_events(limit=max(limit * 10, limit))
        items: List[Dict[str, Any]] = []
        for event in events:
            item = self._to_timeline_view(event)
            if item is None:
                continue
            if source_type and item["source_type"] != source_type:
                continue
            items.append(item)
            if len(items) >= limit:
                break
        return items

    async def count_events(self) -> int:
        """Count all non-deleted events."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            async with db.execute(
                f"SELECT COUNT(*) FROM {FACT_EVENTS_TABLE} WHERE deleted_at IS NULL"
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    def get_statistics(self) -> Dict[str, Any]:
        """Return lightweight runtime stats for reporting and backlog polling."""
        return {
            "db_path": self.db_path,
            "vector_enabled": self._vectors_enabled(),
            "async_embeddings": self._async_embeddings_enabled(),
            "active_embedding_profile_id": self.get_active_embedding_profile_id(),
            "embedding_queue_size": self._embedding_queue.qsize() if self._embedding_queue is not None else 0,
            "embedding_worker_running": any(not worker.done() for worker in self._embedding_workers),
            "embedding_worker_count": self._embedding_worker_count,
        }

    async def list_compressible_event_ids(
        self,
        *,
        older_than: float,
        limit: int = 1000,
    ) -> List[str]:
        """List non-deleted compressible L1 events older than a cutoff timestamp."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            async with db.execute(
                f"""
                SELECT event_id
                FROM {FACT_EVENTS_TABLE}
                WHERE deleted_at IS NULL
                  AND retention_class = ?
                  AND timestamp < ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (
                    int(RetentionClass.COMPRESSIBLE),
                    float(older_than),
                    int(limit),
                ),
            ) as cursor:
                rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]

    async def clear(self) -> int:
        """Delete all events and return the removed count."""
        count = await self.count_events()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute(f"DELETE FROM {FACT_EVENTS_TABLE}")
            await db.execute(f"DELETE FROM {EVENT_CHUNKS_TABLE}")
            await db.execute("DELETE FROM l1_events_fts")
            await db.commit()
        if self._vector_index is not None:
            await self._vector_index.clear()
        return count

    async def rebuild_embeddings(self, *, batch_size: int = 100) -> int:
        """Rebuild all persisted L1 embeddings from the parent event rows."""
        await self.initialize()
        normalized_batch_size = max(1, int(batch_size))
        if not self._vectors_enabled() or self._embedding_service is None or self._vector_index is None:
            return 0

        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute(f"DELETE FROM {EVENT_CHUNKS_TABLE}")
            await db.execute(f"DELETE FROM {EMBEDDING_PROFILES_TABLE}")
            await db.execute(
                f"""
                UPDATE {FACT_EVENTS_TABLE}
                SET embedding_status = ?, embedding_profile_id = NULL, embedding_chunk_count = 0, last_embedded_at = NULL
                WHERE deleted_at IS NULL
                """,
                (EMBEDDING_STATUS_DISABLED,),
            )
            await db.commit()
        await self._vector_index.clear()

        processed = 0
        offset = 0
        while True:
            async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    f"""
                    SELECT *
                    FROM {FACT_EVENTS_TABLE}
                    WHERE deleted_at IS NULL
                    ORDER BY timestamp ASC, id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (normalized_batch_size, offset),
                ) as cursor:
                    rows = await cursor.fetchall()
            if not rows:
                break
            events = [self._row_to_memory_event(row) for row in rows]
            await self._maybe_upsert_event_embeddings(events)
            processed += len(events)
            offset += len(rows)
        return processed

    async def mark_deleted(self, event_id: str, *, deleted_at: Optional[float] = None) -> bool:
        """Soft-delete an event."""
        await self.initialize()
        deleted_timestamp = float(deleted_at or time.time())
        chunk_ids = await self._list_chunk_ids_for_event(event_id)
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            cursor = await db.execute(
                f"UPDATE {FACT_EVENTS_TABLE} SET deleted_at = ? WHERE event_id = ?",
                (deleted_timestamp, event_id),
            )
            if cursor.rowcount > 0:
                await db.execute(
                    "DELETE FROM l1_events_fts WHERE event_id = ?",
                    (event_id,),
                )
                await db.execute(
                    f"DELETE FROM {EVENT_CHUNKS_TABLE} WHERE event_id = ?",
                    (event_id,),
                )
            await db.commit()
        if cursor.rowcount > 0 and self._vector_index is not None:
            for chunk_id in chunk_ids:
                await self._vector_index.delete_entity(entity_id=chunk_id)
        return cursor.rowcount > 0

    async def bm25_search(
        self,
        query: str,
        *,
        limit: int = 20,
        user_id: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        strict: bool = False,
    ) -> List[Tuple[str, float]]:
        """Search L1 events via FTS5 BM25 ranking.

        Returns a list of (event_id, bm25_score) tuples ordered by relevance.
        Lower bm25 scores indicate higher relevance in SQLite FTS5.

        When *user_id* is provided the results are scoped to events owned by
        that user via a JOIN with the fact_events table.

        When *strict* is True the search uses exact token matching first
        (no prefix stemming) and skips the OR / relaxed fallback phases.
        This avoids noise from short prefix stems such as ``crow*`` matching
        unrelated words like *crowd* or *crowded*.
        """
        await self.initialize()
        tokenized = tokenize_for_fts(query)
        if not tokenized:
            return []
        escaped = escape_fts_query(tokenized)
        if not escaped:
            return []
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            try:
                phase = "none"
                _time_kw = {"start_time": start_time, "end_time": end_time}
                rows: list = []
                stemmed = ""
                # Phase 0 (strict-first): Exact AND query — no prefix truncation
                if strict:
                    exact = build_exact_fts_query(escaped)
                    if exact:
                        rows = await self._run_bm25_query(db, exact, limit=limit, user_id=user_id, **_time_kw)
                        if rows:
                            phase = "exact_and"
                # Phase 1: Stemmed AND query (stop words removed, inflections expanded)
                if not rows:
                    stemmed = build_stemmed_fts_query(escaped)
                    if stemmed:
                        rows = await self._run_bm25_query(db, stemmed, limit=limit, user_id=user_id, **_time_kw)
                        if rows:
                            phase = "stemmed_and"
                    else:
                        stemmed = ""
                # Phase 2: Original escaped query (for CJK / non-English text)
                if not rows:
                    rows = await self._run_bm25_query(db, escaped, limit=limit, user_id=user_id, **_time_kw)
                    if rows:
                        phase = "original_and"
                # Phase 3 & 4: Relaxed / OR fallback — skipped in strict mode
                if not strict:
                    # Phase 3: Relaxed phrase queries (quoted spans)
                    if not rows:
                        for fallback_query in self._build_relaxed_fts_queries(query):
                            rows = await self._run_bm25_query(db, fallback_query, limit=limit, user_id=user_id, **_time_kw)
                            if rows:
                                phase = "relaxed_phrase"
                                break
                    # Phase 4: OR fallback with stop words removed and stems added
                    if not rows:
                        or_query = build_or_fts_query(escaped)
                        if or_query and or_query != escaped:
                            rows = await self._run_bm25_query(db, or_query, limit=limit, user_id=user_id, **_time_kw)
                            if rows:
                                phase = "or_fallback"
                logger.info(
                    "BM25 search completed | phase=%s escaped=%r stemmed=%r "
                    "result_count=%d user_id=%s",
                    phase, escaped, stemmed, len(rows), user_id,
                )
                return [(str(row[0]), float(row[1])) for row in rows]
            except Exception as exc:
                logger.warning("FTS5 BM25 search failed: %s", exc)
                return []

    async def _run_bm25_query(
        self,
        db: aiosqlite.Connection,
        match_query: str,
        *,
        limit: int,
        user_id: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> list[tuple[Any, Any]]:
        """Execute a single FTS5 BM25 query.

        When *user_id* is provided the FTS5 results are joined with
        ``fact_events`` so only events belonging to that user are ranked.
        When *start_time* / *end_time* are given, results are constrained
        to the timestamp range via ``fact_events.timestamp``.
        """
        if user_id:
            clauses = [
                "l1_events_fts MATCH ?",
                "fe.user_id = ?",
                "fe.deleted_at IS NULL",
            ]
            params: list[Any] = [match_query, user_id]
            if start_time is not None:
                clauses.append("fe.timestamp >= ?")
                params.append(start_time)
            if end_time is not None:
                clauses.append("fe.timestamp <= ?")
                params.append(end_time)
            params.append(limit)
            where = " AND ".join(clauses)
            async with db.execute(
                f"""
                SELECT fts.event_id, bm25(l1_events_fts) AS score
                FROM l1_events_fts fts
                JOIN fact_events fe ON fe.event_id = fts.event_id
                WHERE {where}
                ORDER BY score
                LIMIT ?
                """,
                tuple(params),
            ) as cursor:
                return await cursor.fetchall()
        async with db.execute(
            """
            SELECT event_id, bm25(l1_events_fts) AS score
            FROM l1_events_fts
            WHERE l1_events_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (match_query, limit),
        ) as cursor:
            return await cursor.fetchall()

    def _build_relaxed_fts_queries(self, query: str) -> list[str]:
        """Build fallback FTS queries for punctuation-heavy comparison prompts."""
        relaxed_queries: list[str] = []
        phrase_queries: list[str] = []
        for match in re.finditer(r"""["']([^"']{3,})["']""", str(query or "")):
            escaped_phrase = escape_fts_query(tokenize_for_fts(match.group(1)))
            if escaped_phrase:
                phrase_queries.append(f'"{escaped_phrase}"')
        if phrase_queries:
            deduped = list(dict.fromkeys(phrase_queries))
            relaxed_queries.append(" OR ".join(deduped))
        return relaxed_queries

    async def backfill_fts(self, *, batch_size: int = 500) -> int:
        """Backfill the FTS5 index from existing fact_events rows.

        Returns the number of rows indexed.
        """
        await self.initialize()
        indexed = 0
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            async with db.execute(
                f"""
                SELECT event_id, content, author_type, content_type FROM {FACT_EVENTS_TABLE}
                WHERE deleted_at IS NULL
                AND event_id NOT IN (SELECT event_id FROM l1_events_fts)
                """
            ) as cursor:
                batch: list[tuple[str, str]] = []
                async for row in cursor:
                    event_id = str(row[0])
                    content = str(row[1] or "")
                    author_type = str(row[2] or "")
                    content_type = str(row[3] or "")
                    batch.append((event_id, tokenize_for_fts(self._compose_search_text(content, author_type, content_type))))
                    if len(batch) >= batch_size:
                        await db.executemany(
                            "INSERT INTO l1_events_fts(event_id, content) VALUES (?, ?)",
                            batch,
                        )
                        indexed += len(batch)
                        batch.clear()
                if batch:
                    await db.executemany(
                        "INSERT INTO l1_events_fts(event_id, content) VALUES (?, ?)",
                        batch,
                    )
                    indexed += len(batch)
            await db.commit()
        return indexed

    async def _maybe_upsert_event_embedding(self, event: MemoryEvent) -> None:
        await self._maybe_upsert_event_embeddings([event])

    async def _maybe_upsert_event_embeddings(self, events: list[MemoryEvent]) -> None:
        if not self._vectors_enabled():
            return
        pipeline = self._build_embedding_pipeline()
        if pipeline is None:
            return
        eligible_events = [
            event
            for event in events
            if self._embedding_eligible(event)
        ]
        if not eligible_events:
            return
        results = await pipeline.upsert_items(
            [
                EmbeddingPipelineItem(
                    parent_id=event.event_id,
                    chunks=self._build_event_embedding_chunks(event),
                    metadata={
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "source": event.source,
                        "partition_value": event.user_id,
                    },
                    payload=event,
                )
                for event in eligible_events
            ]
        )
        if not results:
            await self._update_event_embedding_states(
                [
                    (event.event_id, EMBEDDING_STATUS_FAILED, self._initial_embedding_profile_id(event), 0, None)
                    for event in eligible_events
                ]
            )
            return
        state_updates: list[tuple[str, str, str | None, int, float | None]] = []
        profiles_by_id: dict[str, EmbeddingProfile] = {}
        successful_events: list[tuple[MemoryEvent, list[ChunkedText], list[Any], EmbeddingProfile]] = []
        failed_events: list[tuple[MemoryEvent, str | None]] = []
        results_by_event_id = {result.parent_id: result for result in results}
        for event in eligible_events:
            result = results_by_event_id.get(event.event_id)
            if result is None:
                failed_events.append((event, self._initial_embedding_profile_id(event)))
                continue
            profile = self._profile_from_embedding_result(result.embeddings[0])
            profiles_by_id[profile.profile_id] = profile
            successful_events.append((event, result.chunks, result.embeddings, profile))
        if successful_events:
            await self._replace_event_chunks(successful_events)
            for event, chunks, _, profile in successful_events:
                embedded_at = results_by_event_id[event.event_id].embedded_at
                state_updates.append((event.event_id, EMBEDDING_STATUS_READY, profile.profile_id, len(chunks), embedded_at))
        for event, profile_id in failed_events:
            state_updates.append((event.event_id, EMBEDDING_STATUS_FAILED, profile_id, 0, None))
        if state_updates:
            await self._update_event_embedding_states(state_updates, profiles_by_id=profiles_by_id)

    def _build_embedding_pipeline(self) -> MemoryEmbeddingPipeline | None:
        if self._embedding_service is None or self._vector_index is None:
            return None
        return MemoryEmbeddingPipeline(
            embedding_service=self._embedding_service,
            vector_index=self._vector_index,
        )

    async def _semantic_search_event_hits(self, *, query: str, limit: int, user_id: str | None = None) -> list[VectorSearchHit]:
        if not self._vectors_enabled() or self._embedding_service is None or self._vector_index is None or not query.strip():
            return []
        embedding = await self._embedding_service.embed_text(query)
        if embedding is None:
            return []
        try:
            return await self._vector_index.search(embedding=embedding, limit=limit, partition_value=user_id)
        except Exception as exc:
            logger.warning("Failed semantic search over L1 events: %s", exc)
            return []

    async def _schedule_event_embedding(self, event: MemoryEvent) -> None:
        if not self._vectors_enabled():
            return
        if self._embedding_queue is not None and self._async_embeddings_enabled():
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
            batch = [item]
            should_stop = False
            batch_size = max(1, int(self._embedding_batch_size))
            deadline = time.monotonic() + max(0.0, float(self._embedding_batch_wait_seconds))
            while len(batch) < batch_size:
                timeout = deadline - time.monotonic()
                if timeout <= 0:
                    break
                try:
                    next_item = await asyncio.wait_for(self._embedding_queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                if next_item is None:
                    self._embedding_queue.task_done()
                    should_stop = True
                    break
                batch.append(next_item)
            try:
                await self._maybe_upsert_event_embeddings(batch)
            finally:
                for _ in batch:
                    self._embedding_queue.task_done()
            if should_stop:
                break

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
        query = f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE deleted_at IS NULL"
        chunk_ids = [hit.entity_id for hit in hits]
        chunk_rows = await self._fetch_chunk_rows_by_ids(chunk_ids)
        chunk_by_id = {str(row["chunk_id"]): row for row in chunk_rows}
        event_id_order: list[str] = []
        chunks_by_event: dict[str, list[dict[str, Any]]] = {}
        best_distance_by_event: dict[str, float] = {}
        for hit in hits:
            row = chunk_by_id.get(hit.entity_id)
            if row is None:
                continue
            event_id = str(row["event_id"])
            if event_id not in chunks_by_event:
                event_id_order.append(event_id)
                chunks_by_event[event_id] = []
                best_distance_by_event[event_id] = hit.distance
            best_distance_by_event[event_id] = min(best_distance_by_event[event_id], hit.distance)
            chunks_by_event[event_id].append(
                {
                    "chunk_id": str(row["chunk_id"]),
                    "chunk_index": int(row["chunk_index"]),
                    "text": str(row["chunk_text"]),
                    "char_start": int(row["char_start"]),
                    "char_end": int(row["char_end"]),
                    "distance": hit.distance,
                }
            )
        if not event_id_order:
            return []

        args: list[Any] = []
        placeholders = ", ".join("?" for _ in event_id_order)
        query += f" AND event_id IN ({placeholders})"
        args.extend(event_id_order)
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

        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        events_by_id = {str(row["event_id"]): self._row_to_dict(row) for row in rows}
        ranked: list[Dict[str, Any]] = []
        for event_id in event_id_order:
            event = events_by_id.get(event_id)
            if event is None:
                continue
            event["distance"] = best_distance_by_event[event_id]
            event["matched_chunks"] = chunks_by_event.get(event_id, [])
            ranked.append(event)
            if len(ranked) >= limit:
                break
        return ranked

    def get_search_text(self, event: MemoryEvent) -> str:
        return self._compose_search_text(event.content, event.author_type, event.content_type)

    def get_embedding_text(self, event: MemoryEvent) -> str:
        return build_l1_embedding_text(event)

    @staticmethod
    def _compose_search_text(content: str, author_type: str, content_type: str) -> str:
        text = str(content or "").strip()
        labels = " ".join(part for part in (str(author_type or "").strip(), str(content_type or "").strip()) if part)
        if text and labels:
            return f"{text} {labels}"
        return text or labels

    def get_active_embedding_profile_id(self) -> str | None:
        profile_id, _ = self._resolve_active_embedding_profile_id()
        return profile_id

    async def _ensure_embedding_status_columns(self, db: aiosqlite.Connection) -> None:
        async with db.execute(f"PRAGMA table_info({FACT_EVENTS_TABLE})") as cursor:
            columns = {str(row[1]) for row in await cursor.fetchall()}
        if "embedding_status" not in columns:
            await db.execute(
                f"ALTER TABLE {FACT_EVENTS_TABLE} ADD COLUMN embedding_status TEXT NOT NULL DEFAULT '{EMBEDDING_STATUS_DISABLED}'"
            )
        if "embedding_profile_id" not in columns:
            await db.execute(
                f"ALTER TABLE {FACT_EVENTS_TABLE} ADD COLUMN embedding_profile_id TEXT"
            )
        if "embedding_chunk_count" not in columns:
            await db.execute(
                f"ALTER TABLE {FACT_EVENTS_TABLE} ADD COLUMN embedding_chunk_count INTEGER NOT NULL DEFAULT 0"
            )
        if "last_embedded_at" not in columns:
            await db.execute(
                f"ALTER TABLE {FACT_EVENTS_TABLE} ADD COLUMN last_embedded_at REAL"
            )

    async def _ensure_metadata_json_column(self, db: aiosqlite.Connection) -> None:
        async with db.execute(f"PRAGMA table_info({FACT_EVENTS_TABLE})") as cursor:
            columns = {str(row[1]) for row in await cursor.fetchall()}
        if "metadata_json" not in columns:
            await db.execute(
                f"ALTER TABLE {FACT_EVENTS_TABLE} ADD COLUMN metadata_json TEXT"
            )

    async def _ensure_event_identity_schema(self, db: aiosqlite.Connection) -> None:
        async with db.execute(f"PRAGMA table_info({FACT_EVENTS_TABLE})") as cursor:
            rows = await cursor.fetchall()
        columns = {str(row[1]) for row in rows}
        if not rows:
            return
        if "id" in columns and "idempotency_key" in columns:
            await db.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS idx_fact_events_business_idempotency "
                f"ON {FACT_EVENTS_TABLE}(source, event_type, idempotency_key)"
            )
            await db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_fact_events_idempotency_key ON {FACT_EVENTS_TABLE}(idempotency_key)"
            )
            return

        has_metadata_json = "metadata_json" in columns
        has_embedding_status = "embedding_status" in columns
        has_embedding_profile_id = "embedding_profile_id" in columns

        await db.executescript(
            f"""
            DROP TABLE IF EXISTS {FACT_EVENTS_TABLE}_migrated;
            CREATE TABLE {FACT_EVENTS_TABLE}_migrated (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                correlation_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                created_at REAL NOT NULL,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                source_item_id TEXT,
                idempotency_key TEXT,
                memory_domain INTEGER NOT NULL,
                ingest_target INTEGER NOT NULL,
                cognition_eligible INTEGER NOT NULL DEFAULT 0,
                tom_depth INTEGER NOT NULL DEFAULT 1,
                retention_class INTEGER NOT NULL DEFAULT 2,
                session_id TEXT,
                turn_id TEXT,
                user_id TEXT,
                task_id TEXT,
                content TEXT NOT NULL,
                author_type TEXT NOT NULL,
                content_type TEXT NOT NULL,
                importance_score REAL NOT NULL DEFAULT 0.5,
                level INTEGER NOT NULL DEFAULT 1,
                media_path TEXT,
                metadata_json TEXT,
                embedding_status TEXT NOT NULL DEFAULT '{EMBEDDING_STATUS_DISABLED}',
                embedding_profile_id TEXT,
                deleted_at REAL
            );
            """
        )
        metadata_json_expr = "metadata_json" if has_metadata_json else "NULL"
        embedding_status_expr = "embedding_status" if has_embedding_status else f"'{EMBEDDING_STATUS_DISABLED}'"
        embedding_profile_expr = "embedding_profile_id" if has_embedding_profile_id else "NULL"
        await db.execute(
            f"""
            INSERT INTO {FACT_EVENTS_TABLE}_migrated(
                event_id, correlation_id, timestamp, created_at,
                event_type, source, source_item_id, idempotency_key, memory_domain, ingest_target,
                cognition_eligible, tom_depth, retention_class, session_id, turn_id, user_id,
                task_id, content, author_type, content_type, importance_score,
                level, media_path, metadata_json, embedding_status, embedding_profile_id, deleted_at
            )
            SELECT
                event_id, correlation_id, timestamp, created_at,
                event_type, source, source_item_id, NULL, memory_domain, ingest_target,
                cognition_eligible, tom_depth, retention_class, session_id, turn_id, user_id,
                task_id, content, author_type, content_type, importance_score,
                level, media_path, {metadata_json_expr}, {embedding_status_expr}, {embedding_profile_expr}, deleted_at
            FROM {FACT_EVENTS_TABLE}
            """
        )
        await db.execute(f"DROP TABLE {FACT_EVENTS_TABLE}")
        await db.execute(f"ALTER TABLE {FACT_EVENTS_TABLE}_migrated RENAME TO {FACT_EVENTS_TABLE}")
        await db.execute(f"CREATE INDEX IF NOT EXISTS idx_fact_events_timestamp ON {FACT_EVENTS_TABLE}(timestamp)")
        await db.execute(f"CREATE INDEX IF NOT EXISTS idx_fact_events_type ON {FACT_EVENTS_TABLE}(event_type)")
        await db.execute(f"CREATE INDEX IF NOT EXISTS idx_fact_events_source ON {FACT_EVENTS_TABLE}(source)")
        await db.execute(f"CREATE INDEX IF NOT EXISTS idx_fact_events_idempotency_key ON {FACT_EVENTS_TABLE}(idempotency_key)")
        await db.execute(f"CREATE INDEX IF NOT EXISTS idx_fact_events_domain ON {FACT_EVENTS_TABLE}(memory_domain)")
        await db.execute(f"CREATE INDEX IF NOT EXISTS idx_fact_events_session ON {FACT_EVENTS_TABLE}(session_id)")
        await db.execute(f"CREATE INDEX IF NOT EXISTS idx_fact_events_turn ON {FACT_EVENTS_TABLE}(turn_id)")
        await db.execute(f"CREATE INDEX IF NOT EXISTS idx_fact_events_user ON {FACT_EVENTS_TABLE}(user_id)")
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_fact_events_importance ON {FACT_EVENTS_TABLE}(importance_score DESC)"
        )
        await db.execute(f"CREATE INDEX IF NOT EXISTS idx_fact_events_retention ON {FACT_EVENTS_TABLE}(retention_class)")
        await db.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_fact_events_business_idempotency "
            f"ON {FACT_EVENTS_TABLE}(source, event_type, idempotency_key)"
        )

    async def _resolve_existing_event_id(
        self,
        db: aiosqlite.Connection,
        event: MemoryEvent,
    ) -> str | None:
        if event.idempotency_key:
            existing = await self._find_event_id_by_idempotency(
                db,
                source=event.source,
                event_type=event.event_type,
                idempotency_key=event.idempotency_key,
            )
            if existing:
                return existing
        async with db.execute(
            f"SELECT event_id FROM {FACT_EVENTS_TABLE} WHERE event_id = ?",
            (event.event_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return str(row[0])

    async def _find_event_id_by_idempotency(
        self,
        db: aiosqlite.Connection,
        *,
        source: str,
        event_type: str,
        idempotency_key: str,
    ) -> str | None:
        async with db.execute(
            f"""
            SELECT event_id
            FROM {FACT_EVENTS_TABLE}
            WHERE source = ? AND event_type = ? AND idempotency_key = ?
            LIMIT 1
            """,
            (source, event_type, idempotency_key),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return str(row[0])

    def _embedding_eligible(self, event: MemoryEvent) -> bool:
        return event.memory_domain not in {MemoryDomain.RUNTIME_TELEMETRY, MemoryDomain.SYSTEM_CONTROL}

    def _initial_embedding_status(self, event: MemoryEvent) -> str:
        if not self._vectors_enabled() or self._embedding_service is None:
            return EMBEDDING_STATUS_DISABLED
        if not self._embedding_eligible(event):
            return EMBEDDING_STATUS_SKIPPED
        return EMBEDDING_STATUS_PENDING

    def _initial_embedding_profile_id(self, event: MemoryEvent) -> str | None:
        if not self._vectors_enabled() or self._embedding_service is None or not self._embedding_eligible(event):
            return None
        return self.get_active_embedding_profile_id()

    def _profile_from_embedding_result(self, embedding: Any) -> EmbeddingProfile:
        if self._embedding_service is not None and hasattr(self._embedding_service, "profile_from_result"):
            return self._embedding_service.profile_from_result(
                embedding,
                text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
            )
        return EmbeddingProfile.build(
            provider_name="unknown",
            model_name=str(getattr(embedding, "model_name", "embedding")),
            dimension=int(getattr(embedding, "dimension", 0) or 0),
            text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
        )

    async def _update_event_embedding_states(
        self,
        updates: list[tuple[str, str, str | None, int, float | None]],
        *,
        profiles_by_id: dict[str, EmbeddingProfile] | None = None,
    ) -> None:
        if not updates:
            return
        profile_ids = {profile_id for _, _, profile_id, _, _ in updates if profile_id}
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            if profile_ids:
                await self._sync_embedding_profiles(db, profile_ids, profiles_by_id=profiles_by_id or {})
            await db.executemany(
                f"""
                UPDATE {FACT_EVENTS_TABLE}
                SET embedding_status = ?, embedding_profile_id = ?, embedding_chunk_count = ?, last_embedded_at = ?
                WHERE event_id = ?
                """,
                [
                    (status, profile_id, int(chunk_count), embedded_at, event_id)
                    for event_id, status, profile_id, chunk_count, embedded_at in updates
                ],
            )
            await db.commit()

    async def _sync_embedding_profiles(
        self,
        db: aiosqlite.Connection,
        profile_ids: set[str],
        *,
        profiles_by_id: dict[str, EmbeddingProfile],
    ) -> None:
        active_profile = None
        if self._embedding_service is not None and hasattr(self._embedding_service, "get_active_profile"):
            active_profile = self._embedding_service.get_active_profile(
                text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION
            )
        if active_profile is not None:
            profiles_by_id[active_profile.profile_id] = active_profile
        now = time.time()
        for profile_id in profile_ids:
            profile = profiles_by_id.get(profile_id)
            if profile is None:
                continue
            await db.execute(
                f"""
                INSERT OR IGNORE INTO {EMBEDDING_PROFILES_TABLE}(
                    profile_id, provider_name, model_name, embedding_dim, text_builder_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.profile_id,
                    profile.provider_name,
                    profile.model_name,
                    profile.dimension,
                    profile.text_builder_version,
                    now,
                ),
            )

    def _effective_embedding_status(
        self,
        stored_status: str,
        stored_profile_id: str | None,
        *,
        active_profile_id: str | None = None,
    ) -> str:
        normalized_status = str(stored_status or EMBEDDING_STATUS_DISABLED)
        if normalized_status != EMBEDDING_STATUS_READY:
            return normalized_status
        if active_profile_id and stored_profile_id and stored_profile_id != active_profile_id:
            return EMBEDDING_STATUS_STALE
        return normalized_status

    def _row_to_dict(
        self,
        row: aiosqlite.Row,
        *,
        include_metadata_json: bool = True,
        include_embedding_fields: bool = True,
        active_embedding_profile_id: str | None = None,
    ) -> Dict[str, Any]:
        stored_profile_id = row["embedding_profile_id"]
        metadata_json = row["metadata_json"] if include_metadata_json else None
        item = {
            "id": int(row["id"]),
            "event_id": str(row["event_id"]),
            "correlation_id": str(row["correlation_id"]),
            "timestamp": float(row["timestamp"]),
            "created_at": float(row["created_at"]),
            "event_type": str(row["event_type"]),
            "source": str(row["source"]),
            "source_item_id": row["source_item_id"],
            "idempotency_key": row["idempotency_key"],
            "memory_domain": MemoryDomain.from_value(row["memory_domain"]).label,
            "ingest_target": IngestTarget.from_value(row["ingest_target"]).label,
            "cognition_eligible": bool(row["cognition_eligible"]),
            "tom_depth": TomDepth.from_value(row["tom_depth"]).label,
            "retention_class": RetentionClass.from_value(row["retention_class"]).label,
            "session_id": row["session_id"],
            "turn_id": row["turn_id"],
            "user_id": row["user_id"],
            "task_id": row["task_id"],
            "content": str(row["content"]),
            "author_type": str(row["author_type"]),
            "content_type": str(row["content_type"]),
            "importance_score": float(row["importance_score"]),
            "level": int(row["level"]),
            "media_path": row["media_path"],
            "metadata_json": json.loads(str(metadata_json)) if metadata_json else None,
            "embedding_chunk_count": int(row["embedding_chunk_count"] or 0),
            "last_embedded_at": float(row["last_embedded_at"]) if row["last_embedded_at"] is not None else None,
            "deleted_at": float(row["deleted_at"]) if row["deleted_at"] is not None else None,
        }
        if include_embedding_fields:
            item["embedding_status"] = self._effective_embedding_status(
                row["embedding_status"],
                stored_profile_id,
                active_profile_id=active_embedding_profile_id,
            )
            item["embedding_profile_id"] = stored_profile_id
        return item

    def _row_to_memory_event(self, row: aiosqlite.Row) -> MemoryEvent:
        stored_profile_id = row["embedding_profile_id"]
        metadata_json = row["metadata_json"]
        return MemoryEvent(
            id=int(row["id"]),
            event_id=str(row["event_id"]),
            correlation_id=str(row["correlation_id"]),
            timestamp=float(row["timestamp"]),
            created_at=float(row["created_at"]),
            event_type=str(row["event_type"]),
            source=str(row["source"]),
            source_item_id=row["source_item_id"],
            idempotency_key=row["idempotency_key"],
            memory_domain=MemoryDomain.from_value(row["memory_domain"]),
            ingest_target=IngestTarget.from_value(row["ingest_target"]),
            cognition_eligible=bool(row["cognition_eligible"]),
            tom_depth=TomDepth.from_value(row["tom_depth"]),
            retention_class=RetentionClass.from_value(row["retention_class"]),
            session_id=row["session_id"],
            turn_id=row["turn_id"],
            user_id=row["user_id"],
            task_id=row["task_id"],
            content=str(row["content"]),
            author_type=str(row["author_type"]),
            content_type=str(row["content_type"]),
            importance_score=float(row["importance_score"]),
            level=int(row["level"]),
            media_path=row["media_path"],
            metadata_json=json.loads(str(metadata_json)) if metadata_json else None,
            embedding_status=self._effective_embedding_status(row["embedding_status"], stored_profile_id),
            embedding_profile_id=stored_profile_id,
        )

    def _build_event_embedding_chunks(self, event: MemoryEvent) -> list[ChunkedText]:
        return chunk_sentences(self.get_embedding_text(event))

    def _chunk_id_for_event(self, event_id: str, chunk_index: int) -> str:
        return f"{event_id}::chunk-{chunk_index}"

    async def _replace_event_chunks(
        self,
        entries: list[tuple[MemoryEvent, list[ChunkedText], list[Any], EmbeddingProfile]],
    ) -> None:
        if not entries:
            return
        now = time.time()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            for event, chunks, _, profile in entries:
                await db.execute(
                    f"DELETE FROM {EVENT_CHUNKS_TABLE} WHERE event_id = ?",
                    (event.event_id,),
                )
                await db.executemany(
                    f"""
                    INSERT INTO {EVENT_CHUNKS_TABLE}(
                        chunk_id, event_id, chunk_index, chunk_text, char_start, char_end,
                        token_estimate, embedding_profile_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            self._chunk_id_for_event(event.event_id, chunk.chunk_index),
                            event.event_id,
                            chunk.chunk_index,
                            chunk.text,
                            chunk.char_start,
                            chunk.char_end,
                            chunk.token_estimate,
                            profile.profile_id,
                            now,
                            now,
                        )
                        for chunk in chunks
                    ],
                )
            await db.commit()

    async def _fetch_chunk_rows_by_ids(self, chunk_ids: list[str]) -> list[aiosqlite.Row]:
        if not chunk_ids:
            return []
        placeholders = ", ".join("?" for _ in chunk_ids)
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT chunk_id, event_id, chunk_index, chunk_text, char_start, char_end
                FROM {EVENT_CHUNKS_TABLE}
                WHERE chunk_id IN ({placeholders})
                """,
                tuple(chunk_ids),
            ) as cursor:
                return await cursor.fetchall()

    async def _list_chunk_ids_for_event(self, event_id: str) -> list[str]:
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            async with db.execute(
                f"SELECT chunk_id FROM {EVENT_CHUNKS_TABLE} WHERE event_id = ?",
                (event_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]

    @staticmethod
    def _to_timeline_view(event: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if event is None:
            return None
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        if not metadata:
            metadata = event.get("metadata_json") if isinstance(event.get("metadata_json"), dict) else {}
        timeline = metadata.get("timeline") if isinstance(metadata.get("timeline"), dict) else {}
        if not timeline:
            return None
        return {
            "event_id": str(event["event_id"]),
            "source_type": str(timeline.get("source_type") or event.get("source") or "memory"),
            "source_item_id": (
                timeline.get("source_item_id")
                or event.get("source_item_id")
                or event.get("idempotency_key")
            ),
            "occurred_at": float(event.get("timestamp") or event.get("created_at") or 0.0),
            "title": str(timeline.get("title") or event.get("content") or event.get("event_id") or "Event"),
            "summary": str(timeline.get("summary") or event.get("content") or ""),
        }


__all__ = ["L1EventStore"]
