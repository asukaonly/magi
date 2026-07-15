"""L4 procedural memory store."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from ..embedding.embedding_service import MemoryEmbeddingService
from ..embedding.sqlite_vec_index import SqliteVecIndex
from .embeddings.service import L4SkillEmbeddingMixin
from .lifecycle import L4ProceduralLifecycleMixin
from .recording import L4ProceduralRecordingMixin
from .retrieval.operations import L4ProceduralRetrievalMixin
from .storage.schema import (
    DEFAULT_STRATEGY_EXTRACTION_THRESHOLD,
    MAX_TRACES_PER_SKILL,
    _ADAPTIVE_MAX_THRESHOLD,
)
from .strategy_extraction import L4StrategyExtractor
from .task_preferences import L4TaskPreferenceMixin


class L4ProceduralMemoryStore(
    L4ProceduralLifecycleMixin,
    L4SkillEmbeddingMixin,
    L4TaskPreferenceMixin,
    L4ProceduralRecordingMixin,
    L4ProceduralRetrievalMixin,
):
    """Tracks procedural skills and breaker state from historical attempts."""

    def __init__(
        self,
        *,
        db_path: str = "~/.magi/data/memory/memory.db",
        embedding_service: MemoryEmbeddingService | None = None,
        memory_config_getter: Callable[[], Any] | None = None,
        scenario_llm_pool: Any | None = None,
        vector_enabled: bool = True,
        async_embeddings: bool = True,
        breaker_failure_threshold: int = 3,
        breaker_recovery_successes: int = 2,
        strategy_extraction_threshold: int = DEFAULT_STRATEGY_EXTRACTION_THRESHOLD,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._embedding_service = embedding_service
        self._memory_config_getter = memory_config_getter
        self._strategy_extractor: L4StrategyExtractor | None = (
            L4StrategyExtractor(scenario_llm_pool) if scenario_llm_pool is not None else None
        )
        self._strategy_extraction_threshold = max(1, int(strategy_extraction_threshold))
        self._default_vector_enabled = bool(vector_enabled and embedding_service is not None)
        self._default_async_embeddings = bool(async_embeddings)
        self._vector_index = (
            SqliteVecIndex(
                db_path=self.db_path,
                registry_table="l4_skill_chunk_vectors",
                entity_column="chunk_id",
                vec_table_prefix="l4_skill_chunk_vec",
            )
            if embedding_service is not None or vector_enabled
            else None
        )
        self._embedding_queue: asyncio.Queue[dict[str, Any] | None] | None = (
            asyncio.Queue() if embedding_service is not None else None
        )
        self._embedding_worker: asyncio.Task[None] | None = None
        self._embedding_active_count = 0
        self._embedding_mutation_lock = asyncio.Lock()
        self._operation_guard_factory: Callable[[], Any] | None = None
        self.breaker_failure_threshold = int(breaker_failure_threshold)
        self.breaker_recovery_successes = int(breaker_recovery_successes)
        self._initialized = False

    @asynccontextmanager
    async def embedding_mutation_guard(self) -> AsyncIterator[None]:
        """Serialize skill vector publication and destructive cleanup."""
        async with self._embedding_mutation_lock:
            yield


__all__ = [
    "DEFAULT_STRATEGY_EXTRACTION_THRESHOLD",
    "L4ProceduralMemoryStore",
    "MAX_TRACES_PER_SKILL",
    "_ADAPTIVE_MAX_THRESHOLD",
]
