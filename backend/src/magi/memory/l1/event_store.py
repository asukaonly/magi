"""Canonical L1 event store for normalized memory events."""

from __future__ import annotations

import logging
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ...config.models import EmbeddingBackend
from ...events.events import Event, EventLevel, EventTypes
from ..embedding.embedding_service import MemoryEmbeddingService
from ..embedding.sqlite_vec_index import SqliteVecIndex
from ..event_contracts import (
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    normalize_runtime_event,
)
from ..hybrid_retrieval.fts_utils import tokenize_for_fts
from .chat_sessions import ensure_chat_sessions_schema_async, project_chat_event_to_session
from .event_store_embeddings import L1EventEmbeddingMixin
from .event_store_entities import L1EventEntityMixin
from .event_store_fts import L1EventFtsMixin
from .event_store_rows import L1EventRowMixin
from .event_store_schema import L1EventSchemaMixin

FACT_EVENTS_TABLE = "fact_events"
EMBEDDING_PROFILES_TABLE = "embedding_profiles"
EVENT_CHUNKS_TABLE = "l1_event_chunks"
EMBEDDING_TEXT_BUILDER_VERSION = "l1_content_v2"
EMBEDDING_STATUS_PENDING = "pending"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_FAILED = "failed"
EMBEDDING_STATUS_SKIPPED = "skipped"
EMBEDDING_STATUS_DISABLED = "disabled"
EMBEDDING_QUEUE_MAXSIZE = 512
DEFAULT_EMBEDDING_WORKER_COUNT = 2

logger = logging.getLogger(__name__)

L1_STORE_DIAGNOSTIC_EVENT_TYPES = {
    EventTypes.USER_MESSAGE,
    EventTypes.AI_RESPONSE,
    EventTypes.ACTION_EXECUTED,
}


class L1EventStore(
    L1EventSchemaMixin,
    L1EventEntityMixin,
    L1EventRowMixin,
    L1EventFtsMixin,
    L1EventEmbeddingMixin,
):
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
            await self._backfill_external_owner_user_ids(db)
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
        semantic_hits = await self._semantic_search_event_hits(
            query=query, limit=max(limit * 5, 20)
        )
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

    async def list_events(
        self, *, limit: int = 100, event_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
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
        exclude_memory_domain: Optional[str] = None,
        exclude_retention_class: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_metadata_json: bool = True,
        include_embedding_fields: bool = True,
        order_by: Literal["timestamp_desc", "timestamp_asc", "importance_desc"] = "timestamp_desc",
    ) -> List[Dict[str, Any]]:
        """Query events with SQL-level filters."""
        await self.initialize()
        where_clause, args = self._build_event_filters(
            session_id=session_id,
            user_id=user_id,
            memory_domain=memory_domain,
            event_type=event_type,
            query=query,
            source_filters=source_filters,
            source_item_id=source_item_id,
            idempotency_key=idempotency_key,
            cognition_eligible=cognition_eligible,
            start_time=start_time,
            end_time=end_time,
            exclude_memory_domain=exclude_memory_domain,
            exclude_retention_class=exclude_retention_class,
        )
        sql = f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE {where_clause}"
        order_clause = {
            "timestamp_desc": "timestamp DESC",
            "timestamp_asc": "timestamp ASC",
            "importance_desc": "importance_score DESC, timestamp DESC",
        }.get(order_by, "timestamp DESC")
        sql += f" ORDER BY {order_clause} LIMIT ? OFFSET ?"
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

    async def summarize_event_sources(
        self,
        *,
        source_filters: Optional[List[str]] = None,
        cognition_eligible: Optional[bool] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        exclude_memory_domain: Optional[str] = None,
        exclude_retention_class: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return lightweight source counts for a filtered L1 event window."""
        await self.initialize()
        where_clause, args = self._build_event_filters(
            source_filters=source_filters,
            cognition_eligible=cognition_eligible,
            start_time=start_time,
            end_time=end_time,
            exclude_memory_domain=exclude_memory_domain,
            exclude_retention_class=exclude_retention_class,
        )
        sql = f"""
            SELECT
                source,
                COUNT(*) AS event_count,
                AVG(importance_score) AS avg_importance,
                MIN(timestamp) AS min_timestamp,
                MAX(timestamp) AS max_timestamp
            FROM {FACT_EVENTS_TABLE}
            WHERE {where_clause}
            GROUP BY source
            ORDER BY event_count DESC, source ASC
        """
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [
            {
                "source": str(row["source"] or ""),
                "event_count": int(row["event_count"] or 0),
                "avg_importance": float(row["avg_importance"] or 0.0),
                "min_timestamp": float(row["min_timestamp"])
                if row["min_timestamp"] is not None
                else None,
                "max_timestamp": float(row["max_timestamp"])
                if row["max_timestamp"] is not None
                else None,
            }
            for row in rows
            if str(row["source"] or "").strip()
        ]

    @staticmethod
    def _build_event_filters(
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
        exclude_memory_domain: Optional[str] = None,
        exclude_retention_class: Optional[str] = None,
    ) -> tuple:
        """Build WHERE clause and args for event queries."""
        parts = ["deleted_at IS NULL"]
        args: List[Any] = []
        if session_id:
            parts.append("session_id = ?")
            args.append(session_id)
        if user_id:
            parts.append("user_id = ?")
            args.append(user_id)
        if memory_domain:
            parts.append("memory_domain = ?")
            args.append(int(MemoryDomain.from_value(memory_domain)))
        if event_type:
            parts.append("event_type = ?")
            args.append(event_type)
        if query:
            parts.append("LOWER(content) LIKE ?")
            args.append(f"%{str(query).strip().lower()}%")
        if source_filters:
            placeholders = ", ".join("?" for _ in source_filters)
            parts.append(f"source IN ({placeholders})")
            args.extend(source_filters)
        if source_item_id:
            parts.append("source_item_id = ?")
            args.append(source_item_id)
        if idempotency_key:
            parts.append("idempotency_key = ?")
            args.append(idempotency_key)
        if cognition_eligible is not None:
            parts.append("cognition_eligible = ?")
            args.append(1 if cognition_eligible else 0)
        if start_time is not None:
            parts.append("timestamp >= ?")
            args.append(float(start_time))
        if end_time is not None:
            parts.append("timestamp <= ?")
            args.append(float(end_time))
        if exclude_memory_domain:
            try:
                parts.append("memory_domain != ?")
                args.append(int(MemoryDomain.from_value(exclude_memory_domain)))
            except (ValueError, KeyError):
                pass
        if exclude_retention_class:
            try:
                parts.append("retention_class != ?")
                args.append(int(RetentionClass.from_value(exclude_retention_class)))
            except (ValueError, KeyError):
                pass
        return " AND ".join(parts), args

    async def get_timeline_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Return a minimal timeline-shaped view from canonical L1 columns."""
        event = await self.get_event(event_id)
        return self._to_timeline_view(event)

    async def list_timeline_events(
        self, *, limit: int = 100, source_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
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

    async def count_events(
        self,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        event_type: Optional[str] = None,
        query: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        source_item_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> int:
        """Count events, optionally filtered."""
        await self.initialize()
        where_clause, args = self._build_event_filters(
            session_id=session_id,
            user_id=user_id,
            event_type=event_type,
            query=query,
            source_filters=source_filters,
            source_item_id=source_item_id,
            idempotency_key=idempotency_key,
            start_time=start_time,
            end_time=end_time,
        )
        sql = f"SELECT COUNT(*) FROM {FACT_EVENTS_TABLE} WHERE {where_clause}"
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            async with db.execute(sql, tuple(args)) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    def get_statistics(self) -> Dict[str, Any]:
        """Return lightweight runtime stats for reporting and backlog polling."""
        return {
            "db_path": self.db_path,
            "vector_enabled": self._vectors_enabled(),
            "async_embeddings": self._async_embeddings_enabled(),
            "active_embedding_profile_id": self.get_active_embedding_profile_id(),
            "embedding_queue_size": self._embedding_queue.qsize()
            if self._embedding_queue is not None
            else 0,
            "embedding_worker_running": any(
                not worker.done() for worker in self._embedding_workers
            ),
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
        """Delete all events by dropping and recreating the DB file.

        This is significantly faster than DELETE + VACUUM on large databases
        because it avoids scanning and journaling every row.  The sequence is:
        1. Count events for the return value.
        2. Stop embedding workers and close all open connections (vec index).
        3. Delete the DB file and its WAL/SHM side-files.
        4. Re-run initialize() to recreate the schema and reconnect.
        """
        logger.info("L1EventStore.clear: counting events before wipe")
        count = await self.count_events()
        logger.info("L1EventStore.clear: total=%d, stopping embedding workers", count)

        # Stop embedding workers cleanly before closing connections.
        if self._embedding_queue is not None and self._embedding_workers:
            for _ in self._embedding_workers:
                await self._embedding_queue.put(None)
            await asyncio.gather(*self._embedding_workers, return_exceptions=True)
            self._embedding_workers = []
            logger.info("L1EventStore.clear: embedding workers stopped")

        # Close the vec index's persistent connection.
        if self._vector_index is not None:
            logger.info("L1EventStore.clear: closing vec index connection")
            await self._vector_index.close()

        # Delete the DB file and WAL/SHM side-files.
        db_path = Path(self.db_path)
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(db_path) + suffix)
            if p.exists():
                logger.info("L1EventStore.clear: deleting %s", p)
                p.unlink()

        # Reset initialization flag so initialize() rebuilds the schema.
        self._initialized = False
        logger.info("L1EventStore.clear: reinitializing schema at %s", db_path)

        # Recreate schema and reconnect.
        await self.initialize()
        logger.info("L1EventStore.clear: done, removed %d events", count)

        return count

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


__all__ = ["L1EventStore"]
