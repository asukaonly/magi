"""Lifecycle and runtime configuration helpers for L1 event storage."""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
from pathlib import Path
from typing import Any

from ...config.models import EmbeddingBackend
from ...core.sqlite import sqlite_connection_async
from ..embedding.embedding_service import MemoryEmbeddingService
from ..embedding.sqlite_vec_index import SqliteVecIndex
from ..event_contracts import MemoryEvent
from .embeddings.common import (
    EMBEDDING_TEXT_BUILDER_VERSION,
)

# Compose the canonical L1 schema from the release baseline migration.
_L1_MIGRATION_MODULES = (
    "magi.db.migrations.l1.versions.v1_initial",
)
SCHEMA_SQL = "\n".join(
    importlib.import_module(_module).SCHEMA_SQL for _module in _L1_MIGRATION_MODULES
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
    _operation_guard_factory: Any | None

    def set_operation_guard_factory(self, factory: Any) -> None:
        """Bind the unified clear barrier used by embedding batches."""
        self._operation_guard_factory = factory

    async def initialize(self, *, start_workers: bool = True) -> None:
        """Verify L1 schema (alembic-managed) and start embedding workers."""
        if not self._initialized:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            await self._ensure_schema()
            if self._vector_index is not None and self._embedding_service is not None:
                await self._vector_index.initialize()
            self._initialized = True

        if start_workers and self._embedding_queue is not None and not self._embedding_workers:
            self._embedding_workers = [
                asyncio.create_task(getattr(self, "_run_embedding_worker")())
                for _ in range(self._embedding_worker_count)
            ]

    async def _ensure_schema(self) -> None:
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.executescript(SCHEMA_SQL)
            await db.commit()

    async def shutdown(self) -> None:
        if self._embedding_queue is not None and self._embedding_workers:
            for _ in self._embedding_workers:
                await self._embedding_queue.put(None)
            await asyncio.gather(*self._embedding_workers)
            self._embedding_workers = []
        if self._vector_index is not None:
            await self._vector_index.close()

    async def abort_for_clear(self) -> None:
        """Cancel embedding work and discard queued pre-clear events."""
        workers = list(self._embedding_workers)
        for worker in workers:
            if not worker.done():
                worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        self._embedding_workers = []
        if self._embedding_queue is not None:
            self._embedding_queue = asyncio.Queue(maxsize=self._embedding_queue.maxsize)
        self._embedding_active_count = 0
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
            "embedding_active_count": int(getattr(self, "_embedding_active_count", 0)),
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
