"""Lifecycle and runtime configuration helpers for L1 event storage."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from ...config.models import EmbeddingBackend
from ...core.sqlite import sqlite_connection_async
from ..embedding.embedding_service import MemoryEmbeddingService
from ..embedding.sqlite_vec_index import SqliteVecIndex
from ..event_contracts import MemoryEvent
from .chat_sessions import ensure_chat_sessions_schema_async
from .embeddings.common import (
    EMBEDDING_PROFILES_TABLE,
    EMBEDDING_TEXT_BUILDER_VERSION,
    EVENT_CHUNKS_TABLE,
    FACT_EVENTS_TABLE,
)

EMBEDDING_QUEUE_MAXSIZE = 512
DEFAULT_EMBEDDING_WORKER_COUNT = 2

logger = logging.getLogger(__name__)


class L1EventLifecycleMixin:
    """Initialize L1 schema, embedding workers, and runtime feature flags."""

    db_path: str
    _initialized: bool
    _embedding_service: MemoryEmbeddingService | None
    _memory_config_getter: Any | None
    _default_vector_enabled: bool
    _default_async_embeddings: bool
    _embedding_worker_count: int
    _embedding_queue: asyncio.Queue[MemoryEvent | None] | None
    _embedding_workers: list[asyncio.Task[None]]
    _vector_index: SqliteVecIndex | None

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
            await self._ensure_embedding_status_columns(db)
            await self._ensure_metadata_json_column(db)
            await self._ensure_envelope_columns(db)
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
                asyncio.create_task(getattr(self, "_run_embedding_worker")())
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

    def get_statistics(self) -> dict[str, Any]:
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


__all__ = [
    "DEFAULT_EMBEDDING_WORKER_COUNT",
    "EMBEDDING_QUEUE_MAXSIZE",
    "L1EventLifecycleMixin",
]
