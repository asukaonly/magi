"""Lifecycle and runtime configuration helpers for L4 procedural memory."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...config.models import EmbeddingBackend
from ...core.sqlite import sqlite_connection_async

logger = logging.getLogger(__name__)


class L4ProceduralLifecycleMixin:
    """Initialize procedural-memory storage and resolve runtime feature flags."""

    db_path: str
    _initialized: bool
    _embedding_queue: Any | None
    _embedding_worker: Any | None
    _vector_index: Any | None
    _memory_config_getter: Any | None
    _embedding_service: Any | None
    _default_vector_enabled: bool
    _default_async_embeddings: bool
    _operation_guard_factory: Any | None

    def set_operation_guard_factory(self, factory: Any) -> None:
        """Bind the unified clear barrier used by embedding batches."""
        self._operation_guard_factory = factory

    async def initialize(self) -> None:
        """Create the procedural memory schema."""
        if self._initialized:
            if self._embedding_queue is not None and self._embedding_worker is None:
                import asyncio

                self._embedding_worker = asyncio.create_task(
                    getattr(self, "_run_embedding_worker")()
                )
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path) as db:
            if self._vector_index is not None and self._embedding_service is not None:
                await self._vector_index.initialize()
            await db.commit()
        if self._embedding_queue is not None and self._embedding_worker is None:
            import asyncio

            self._embedding_worker = asyncio.create_task(getattr(self, "_run_embedding_worker")())
        self._initialized = True

    async def shutdown(self) -> None:
        if self._embedding_queue is not None and self._embedding_worker is not None:
            await self._embedding_queue.put(None)
            await self._embedding_worker
            self._embedding_worker = None
        if self._vector_index is not None:
            await self._vector_index.close()

    async def abort_for_clear(self) -> None:
        """Cancel embedding work and discard queued pre-clear skills."""
        worker = self._embedding_worker
        if worker is not None and not worker.done():
            worker.cancel()
        if worker is not None:
            import asyncio

            await asyncio.gather(worker, return_exceptions=True)
        self._embedding_worker = None
        if self._embedding_queue is not None:
            import asyncio

            self._embedding_queue = asyncio.Queue(maxsize=self._embedding_queue.maxsize)
        self._embedding_active_count = 0

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
            and config.l4.enabled
            and config.l4.vectors_enabled
        )

    def _async_embeddings_enabled(self) -> bool:
        config = self._current_memory_config()
        if config is None:
            return self._default_async_embeddings
        return bool(config.async_embeddings)


__all__ = ["L4ProceduralLifecycleMixin"]
