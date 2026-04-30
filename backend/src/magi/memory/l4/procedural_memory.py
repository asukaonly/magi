"""L4 procedural memory store."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ...config.models import EmbeddingBackend
from ..embedding.embedding_service import MemoryEmbeddingService
from ..event_contracts import MemoryEvent
from ..embedding.sqlite_vec_index import SqliteVecIndex
from .retrieval.operations import L4ProceduralRetrievalMixin
from .storage.schema import (
    DEFAULT_STRATEGY_EXTRACTION_THRESHOLD,
    EMBEDDING_TEXT_BUILDER_VERSION,
    MAX_TRACES_PER_SKILL,
    PENDING_TRACE_COUNT_MIGRATION_SQL,
    PROCEDURAL_MEMORY_SCHEMA_SQL,
    TRACE_TURN_ID_MIGRATION_SQL,
    TRACE_TURN_INDEX_SQL,
    _ADAPTIVE_MAX_THRESHOLD,
    ensure_procedural_memory_schema,
)
from .storage.serialization import (
    adaptive_extraction_threshold,
    extract_skill_identity,
)
from .embeddings.service import L4SkillEmbeddingMixin
from .learning.updates import (
    build_new_skill_record_state,
    build_updated_skill_record_state,
)
from .storage.records import (
    insert_new_skill_record,
    sync_skill_fts,
    update_skill_record,
)
from .traces.store import insert_execution_trace
from .strategy_extraction import ExtractedStrategy, L4StrategyExtractor
from .strategy_operations import (
    enrich_with_recovery,
    get_duration_baseline,
    maybe_extract_strategy,
    persist_strategy,
    stratified_traces,
)

logger = logging.getLogger(__name__)


class L4ProceduralMemoryStore(L4SkillEmbeddingMixin, L4ProceduralRetrievalMixin):
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
        self.breaker_failure_threshold = int(breaker_failure_threshold)
        self.breaker_recovery_successes = int(breaker_recovery_successes)
        self._initialized = False

    async def initialize(self) -> None:
        """Create the procedural memory schema."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path) as db:
            await ensure_procedural_memory_schema(db)
            if self._vector_index is not None:
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

    async def record_memory_event(self, event: MemoryEvent) -> Optional[str]:
        """Update procedural memory based on a normalized event."""
        identity = self._extract_skill_identity(event)
        if identity is None:
            return None

        await self.initialize()
        skill_name: str = identity["skill_name"]
        skill_category: str = identity["skill_category"]
        skill_type: str = identity["skill_type"]
        success: bool = identity["success"]
        duration_ms: float = identity["duration_ms"]
        optimized_prompt: Optional[str] = identity["optimized_prompt"]
        now = time.time()

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM procedural_skills WHERE skill_name = ? AND skill_category = ?",
                (skill_name, skill_category),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing is None:
                skill_id = f"skill_{uuid.uuid4().hex}"
                record_state = build_new_skill_record_state(
                    success=success,
                    duration_ms=duration_ms,
                    event_timestamp=float(event.timestamp),
                    breaker_failure_threshold=self.breaker_failure_threshold,
                )
                await insert_new_skill_record(
                    db,
                    skill_id=skill_id,
                    skill_name=skill_name,
                    skill_category=skill_category,
                    skill_type=skill_type,
                    record_state=record_state,
                    optimized_prompt=optimized_prompt,
                    event_id=event.event_id,
                    event_timestamp=float(event.timestamp),
                    now=now,
                )
                await db.commit()
                await sync_skill_fts(
                    db,
                    skill_id=skill_id,
                    skill_name=skill_name,
                    skill_category=skill_category,
                    optimized_prompt=optimized_prompt,
                    replace_existing=False,
                )
                await db.commit()
                await self._schedule_skill_embedding(
                    skill_id=skill_id,
                    skill_name=skill_name,
                    skill_category=skill_category,
                    optimized_prompt=optimized_prompt,
                )
                await insert_execution_trace(
                    db_path=self.db_path,
                    skill_id=skill_id,
                    event=event,
                    identity=identity,
                )
                return skill_id

            record_state = build_updated_skill_record_state(
                existing=existing,
                success=success,
                duration_ms=duration_ms,
                event_id=event.event_id,
                event_timestamp=float(event.timestamp),
                breaker_failure_threshold=self.breaker_failure_threshold,
                breaker_recovery_successes=self.breaker_recovery_successes,
            )

            skill_id = str(existing["skill_id"])
            await update_skill_record(
                db,
                skill_id=skill_id,
                record_state=record_state,
                optimized_prompt=optimized_prompt,
                event_timestamp=float(event.timestamp),
                now=now,
            )
            await db.commit()
            await sync_skill_fts(
                db,
                skill_id=skill_id,
                skill_name=skill_name,
                skill_category=skill_category,
                optimized_prompt=optimized_prompt or existing["optimized_prompt"],
                replace_existing=True,
            )
            await db.commit()
            await self._schedule_skill_embedding(
                skill_id=skill_id,
                skill_name=skill_name,
                skill_category=skill_category,
                optimized_prompt=optimized_prompt or existing["optimized_prompt"],
            )
            await insert_execution_trace(
                db_path=self.db_path,
                skill_id=skill_id,
                event=event,
                identity=identity,
            )
            adaptive_threshold = self._adaptive_extraction_threshold(
                self._strategy_extraction_threshold, record_state.total_attempts,
            )
            if record_state.pending_trace_count >= adaptive_threshold or record_state.breaker_just_opened:
                await self._maybe_extract_strategy(
                    skill_id=skill_id,
                    skill_name=skill_name,
                    skill_category=skill_category,
                    total_attempts=record_state.total_attempts,
                    success_rate=record_state.success_rate,
                )
            return skill_id

    @staticmethod
    def _adaptive_extraction_threshold(
        base_threshold: int,
        total_attempts: int,
    ) -> int:
        """Scale extraction threshold with usage volume.

        Low-usage tools keep the base threshold (e.g. 5).  High-frequency
        tools (like ``bash``) get a progressively higher threshold so
        extraction runs less often.  The formula is roughly
        ``base * sqrt(total / base)`` clamped to [base, MAX].
        """
        return adaptive_extraction_threshold(base_threshold, total_attempts)

    async def _stratified_traces(
        self,
        skill_id: str,
        *,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Return a diverse sample of traces for strategy extraction.

        Instead of just the latest N traces, samples from three buckets:
        1. Recent failures (up to limit//3)
        2. Recent successes (up to limit//3)
        3. Most recent traces regardless of outcome (remaining slots)

        This ensures the LLM sees failure patterns even for tools with
        high success rates, and vice versa.
        """
        await self.initialize()
        return await stratified_traces(db_path=self.db_path, skill_id=skill_id, limit=limit)

    def _extract_skill_identity(
        self,
        event: MemoryEvent,
    ) -> Optional[Dict[str, Any]]:
        return extract_skill_identity(event)

    async def _maybe_extract_strategy(
        self,
        *,
        skill_id: str,
        skill_name: str,
        skill_category: str,
        total_attempts: int,
        success_rate: float,
    ) -> None:
        """Conditionally run LLM strategy extraction and persist the result."""
        await maybe_extract_strategy(
            db_path=self.db_path,
            strategy_extractor=self._strategy_extractor,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_category=skill_category,
            total_attempts=total_attempts,
            success_rate=success_rate,
        )

    async def _get_duration_baseline(self, skill_id: str) -> Dict[str, float]:
        """Return avg and p95 execution times for a skill."""
        return await get_duration_baseline(db_path=self.db_path, skill_id=skill_id)

    async def _enrich_with_recovery(
        self,
        traces: List[Dict[str, Any]],
        current_skill_id: str,
    ) -> None:
        """Annotate failure traces with same-turn successful recovery by other tools.

        For each failure trace that has a ``turn_id``, look for a subsequent
        success from a *different* skill in the same turn.  If found, add
        ``recovery_tool`` and ``recovery_output`` keys to the trace dict.
        """
        await enrich_with_recovery(
            db_path=self.db_path,
            traces=traces,
            current_skill_id=current_skill_id,
        )

    async def _persist_strategy(
        self,
        *,
        skill_id: str,
        strategy: ExtractedStrategy,
    ) -> None:
        """Write extracted strategy to the procedural_skills row and reset pending count."""
        await persist_strategy(db_path=self.db_path, skill_id=skill_id, strategy=strategy)

__all__ = ["L4ProceduralMemoryStore"]
