"""L4 procedural memory store."""

from __future__ import annotations

import json
import logging
import asyncio
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ...config.models import EmbeddingBackend
from ..embedding.chunking import ChunkedText, chunk_text
from ..embedding.embedding_pipeline import EmbeddingPipelineItem, MemoryEmbeddingPipeline
from ..embedding.embedding_text_builders import build_l4_embedding_text
from ..embedding.embedding_service import EmbeddingProfile, MemoryEmbeddingService
from ..event_contracts import MemoryEvent
from ..hybrid_retrieval.fts_utils import escape_fts_query, tokenize_for_fts
from ..embedding.sqlite_vec_index import SqliteVecIndex, VectorSearchHit
from .strategy_extraction import ExtractedStrategy, L4StrategyExtractor

logger = logging.getLogger(__name__)

SKILL_CHUNKS_TABLE = "l4_skill_chunks"
EXECUTION_TRACES_TABLE = "l4_execution_traces"
EMBEDDING_TEXT_BUILDER_VERSION = "l4_skill_v1"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_DISABLED = "disabled"

# Trace pruning: keep at most this many traces per skill.
MAX_TRACES_PER_SKILL = 50

# Default threshold: extract strategy after this many new traces.
DEFAULT_STRATEGY_EXTRACTION_THRESHOLD = 5


def _truncate(value: Any, max_chars: int) -> Optional[str]:
    """Truncate a value to a string of at most *max_chars* characters."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."


class L4ProceduralMemoryStore:
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
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS procedural_skills (
                    skill_id TEXT PRIMARY KEY,
                    skill_name TEXT NOT NULL,
                    skill_category TEXT NOT NULL,
                    skill_type TEXT NOT NULL,
                    proficiency REAL NOT NULL DEFAULT 0.0,
                    total_attempts INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    success_rate REAL NOT NULL DEFAULT 0.0,
                    avg_execution_time_ms REAL,
                    min_execution_time_ms REAL,
                    max_execution_time_ms REAL,
                    p95_execution_time_ms REAL,
                    circuit_breaker_state TEXT NOT NULL DEFAULT 'closed',
                    circuit_breaker_opened_at REAL,
                    circuit_breaker_failure_count INTEGER NOT NULL DEFAULT 0,
                    circuit_breaker_success_count INTEGER NOT NULL DEFAULT 0,
                    optimized_prompt TEXT,
                    optimized_params TEXT,
                    optimization_score REAL,
                    context_affinity TEXT,
                    source_event_ids TEXT NOT NULL,
                    last_used_at REAL,
                    last_success_at REAL,
                    last_failure_at REAL,
                    embedding_status TEXT NOT NULL DEFAULT 'disabled',
                    embedding_profile_id TEXT,
                    embedding_chunk_count INTEGER NOT NULL DEFAULT 0,
                    last_embedded_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(skill_name, skill_category)
                );
                CREATE INDEX IF NOT EXISTS idx_procedural_skill_name ON procedural_skills(skill_name, skill_category);

                CREATE TABLE IF NOT EXISTS l4_skill_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    skill_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL,
                    char_start INTEGER NOT NULL,
                    char_end INTEGER NOT NULL,
                    token_estimate INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_l4_skill_chunks_skill ON l4_skill_chunks(skill_id);
                CREATE INDEX IF NOT EXISTS idx_l4_skill_chunks_index ON l4_skill_chunks(skill_id, chunk_index);

                CREATE VIRTUAL TABLE IF NOT EXISTS l4_skills_fts USING fts5(
                    skill_id UNINDEXED,
                    content,
                    tokenize='unicode61'
                );

                CREATE TABLE IF NOT EXISTS l4_execution_traces (
                    trace_id TEXT PRIMARY KEY,
                    skill_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    duration_ms REAL,
                    error_summary TEXT,
                    input_summary TEXT,
                    output_summary TEXT,
                    task_context TEXT,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_l4_traces_skill
                    ON l4_execution_traces(skill_id, created_at DESC);
                """
            )
            # Add pending_trace_count column if missing (migration-safe).
            try:
                await db.execute(
                    "ALTER TABLE procedural_skills ADD COLUMN pending_trace_count INTEGER NOT NULL DEFAULT 0"
                )
            except Exception:
                pass  # Column already exists
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
                total_attempts = 1
                success_count = 1 if success else 0
                failure_count = 0 if success else 1
                avg_duration = duration_ms
                min_duration = duration_ms
                max_duration = duration_ms
                breaker_state = "closed"
                breaker_opened_at = None
                failure_streak = 0 if success else 1
                recovery_count = 0
                if failure_streak >= self.breaker_failure_threshold:
                    breaker_state = "open"
                    breaker_opened_at = event.timestamp
                await db.execute(
                    """
                    INSERT INTO procedural_skills(
                        skill_id, skill_name, skill_category, skill_type, proficiency,
                        total_attempts, success_count, failure_count, success_rate,
                        avg_execution_time_ms, min_execution_time_ms, max_execution_time_ms, p95_execution_time_ms,
                        circuit_breaker_state, circuit_breaker_opened_at, circuit_breaker_failure_count,
                        circuit_breaker_success_count, optimized_prompt, optimized_params, optimization_score,
                        context_affinity, source_event_ids, last_used_at, last_success_at, last_failure_at,
                        embedding_chunk_count, last_embedded_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        skill_id,
                        skill_name,
                        skill_category,
                        skill_type,
                        float(success_count / total_attempts),
                        total_attempts,
                        success_count,
                        failure_count,
                        float(success_count / total_attempts),
                        duration_ms,
                        duration_ms,
                        duration_ms,
                        duration_ms,
                        breaker_state,
                        breaker_opened_at,
                        failure_streak,
                        recovery_count,
                        optimized_prompt,
                        json.dumps({}, ensure_ascii=False),
                        None,
                        json.dumps({}, ensure_ascii=False),
                        json.dumps([event.event_id], ensure_ascii=False),
                        float(event.timestamp),
                        float(event.timestamp) if success else None,
                        float(event.timestamp) if not success else None,
                        0,
                        None,
                        now,
                        now,
                    ),
                )
                await db.commit()
                # Sync FTS5 index (new skill)
                fts_text = tokenize_for_fts(f"{skill_name} {skill_category} {optimized_prompt or ''}")
                await db.execute(
                    "INSERT OR REPLACE INTO l4_skills_fts(skill_id, content) VALUES (?, ?)",
                    (skill_id, fts_text),
                )
                await db.commit()
                await self._schedule_skill_embedding(
                    skill_id=skill_id,
                    skill_name=skill_name,
                    skill_category=skill_category,
                    optimized_prompt=optimized_prompt,
                )
                await self._insert_execution_trace(
                    skill_id=skill_id,
                    event=event,
                    identity=identity,
                )
                return skill_id

            total_attempts = int(existing["total_attempts"]) + 1
            success_count = int(existing["success_count"]) + (1 if success else 0)
            failure_count = int(existing["failure_count"]) + (0 if success else 1)
            avg_duration = self._rolling_average(existing["avg_execution_time_ms"], total_attempts - 1, duration_ms)
            min_duration = min(float(existing["min_execution_time_ms"] or duration_ms), duration_ms)
            max_duration = max(float(existing["max_execution_time_ms"] or duration_ms), duration_ms)
            source_event_ids = json.loads(existing["source_event_ids"] or "[]")
            source_event_ids.append(event.event_id)
            breaker_state = str(existing["circuit_breaker_state"])
            failure_streak = int(existing["circuit_breaker_failure_count"])
            recovery_count = int(existing["circuit_breaker_success_count"])
            breaker_opened_at = float(existing["circuit_breaker_opened_at"]) if existing["circuit_breaker_opened_at"] else None

            if success:
                failure_streak = 0
                if breaker_state == "open":
                    breaker_state = "half_open"
                    recovery_count = 1
                elif breaker_state == "half_open":
                    recovery_count += 1
                    if recovery_count >= self.breaker_recovery_successes:
                        breaker_state = "closed"
                        recovery_count = 0
                        breaker_opened_at = None
                else:
                    recovery_count = 0
            else:
                recovery_count = 0
                failure_streak += 1
                if failure_streak >= self.breaker_failure_threshold:
                    breaker_state = "open"
                    breaker_opened_at = event.timestamp

            await db.execute(
                """
                UPDATE procedural_skills
                SET proficiency = ?, total_attempts = ?, success_count = ?, failure_count = ?, success_rate = ?,
                    avg_execution_time_ms = ?, min_execution_time_ms = ?, max_execution_time_ms = ?, p95_execution_time_ms = ?,
                    circuit_breaker_state = ?, circuit_breaker_opened_at = ?, circuit_breaker_failure_count = ?,
                    circuit_breaker_success_count = ?, optimized_prompt = COALESCE(?, optimized_prompt),
                    source_event_ids = ?, last_used_at = ?, last_success_at = ?, last_failure_at = ?, updated_at = ?,
                    pending_trace_count = COALESCE(pending_trace_count, 0) + 1
                WHERE skill_id = ?
                """,
                (
                    float(success_count / total_attempts),
                    total_attempts,
                    success_count,
                    failure_count,
                    float(success_count / total_attempts),
                    avg_duration,
                    min_duration,
                    max_duration,
                    max_duration,
                    breaker_state,
                    breaker_opened_at,
                    failure_streak,
                    recovery_count,
                    optimized_prompt,
                    json.dumps(source_event_ids[-100:], ensure_ascii=False),
                    float(event.timestamp),
                    float(event.timestamp) if success else existing["last_success_at"],
                    float(event.timestamp) if not success else existing["last_failure_at"],
                    now,
                    str(existing["skill_id"]),
                ),
            )
            await db.commit()
            # Sync FTS5 index (updated skill)
            fts_text = tokenize_for_fts(
                f"{skill_name} {skill_category} {optimized_prompt or existing['optimized_prompt'] or ''}"
            )
            await db.execute(
                "DELETE FROM l4_skills_fts WHERE skill_id = ?",
                (str(existing["skill_id"]),),
            )
            await db.execute(
                "INSERT INTO l4_skills_fts(skill_id, content) VALUES (?, ?)",
                (str(existing["skill_id"]), fts_text),
            )
            await db.commit()
            await self._schedule_skill_embedding(
                skill_id=str(existing["skill_id"]),
                skill_name=skill_name,
                skill_category=skill_category,
                optimized_prompt=optimized_prompt or existing["optimized_prompt"],
            )
            await self._insert_execution_trace(
                skill_id=str(existing["skill_id"]),
                event=event,
                identity=identity,
            )
            # Trigger strategy extraction if enough new traces accumulated
            # or circuit breaker just opened.
            pending = (existing["pending_trace_count"] or 0) + 1
            breaker_just_opened = (
                breaker_state == "open"
                and str(existing["circuit_breaker_state"]) != "open"
            )
            if pending >= self._strategy_extraction_threshold or breaker_just_opened:
                await self._maybe_extract_strategy(
                    skill_id=str(existing["skill_id"]),
                    skill_name=skill_name,
                    skill_category=skill_category,
                    total_attempts=total_attempts,
                    success_rate=float(success_count / total_attempts),
                )
            return str(existing["skill_id"])

    async def get_skill(self, *, skill_name: str, skill_category: str) -> Optional[Dict[str, Any]]:
        """Fetch a single procedural skill."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM procedural_skills WHERE skill_name = ? AND skill_category = ?",
                (skill_name, skill_category),
            ) as cursor:
                row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def count_skills(self) -> int:
        """Count all procedural skills."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM procedural_skills") as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def get_all_skills(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        """List all stored skills."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM procedural_skills ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (int(limit), int(offset)),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def get_tool_advisory(
        self,
        tool_names: List[str],
        task_context: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Return lightweight advisory for each requested tool.

        Each advisory dict contains:
            tool_name, available (bool), breaker_state, success_rate,
            total_attempts, strategy_hint, context_fit, risk_note
        """
        if not tool_names:
            return []
        await self.initialize()
        placeholders = ", ".join("?" for _ in tool_names)
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT skill_name, circuit_breaker_state, success_rate,
                       total_attempts, optimized_prompt, context_affinity,
                       failure_count, last_failure_at
                FROM procedural_skills
                WHERE skill_category = 'tool' AND skill_name IN ({placeholders})
                """,
                tuple(tool_names),
            ) as cursor:
                rows = await cursor.fetchall()

        known = {str(row["skill_name"]): row for row in rows}
        result: List[Dict[str, Any]] = []

        for name in tool_names:
            row = known.get(name)
            if row is None:
                # Tool has no execution history — no advisory.
                continue

            breaker = str(row["circuit_breaker_state"])
            available = breaker != "open"
            success_rate = float(row["success_rate"])
            total_attempts = int(row["total_attempts"])

            # Extract strategy hint from optimized_prompt (may be JSON or plain text).
            strategy_hint = self._extract_strategy_hint(row["optimized_prompt"])

            # Compute context fit if task_context provided.
            context_fit = self._compute_context_fit(
                row["context_affinity"], task_context
            )

            # Build risk note.
            risk_note = None
            if breaker == "open":
                risk_note = "Circuit breaker open: consecutive failures detected"
            elif breaker == "half_open":
                risk_note = "Circuit breaker recovering: recent failures observed"
            elif success_rate < 0.5 and total_attempts >= 3:
                risk_note = f"Low success rate ({success_rate:.0%} over {total_attempts} attempts)"

            result.append(
                {
                    "tool_name": name,
                    "available": available,
                    "breaker_state": breaker,
                    "success_rate": success_rate,
                    "total_attempts": total_attempts,
                    "strategy_hint": strategy_hint,
                    "context_fit": context_fit,
                    "risk_note": risk_note,
                }
            )

        return result

    @staticmethod
    def _extract_strategy_hint(optimized_prompt: str | None) -> str | None:
        """Extract a short hint from the strategy JSON or raw text."""
        if not optimized_prompt:
            return None
        text = str(optimized_prompt).strip()
        # Try parsing as strategy JSON (new format).
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                approach = str(data.get("recommended_approach") or "").strip()
                if approach:
                    return approach
                # Fall back to first best_use_case.
                cases = data.get("best_use_cases") or []
                if cases:
                    return str(cases[0]).strip()
                return None
        except (json.JSONDecodeError, TypeError):
            pass
        # Legacy plain-text prompt — return truncated.
        if len(text) > 200:
            return text[:197] + "..."
        return text

    @staticmethod
    def _compute_context_fit(
        context_affinity_json: str | None,
        task_context: str | None,
    ) -> float | None:
        """Compute 0-1 context fit from stored affinity and current task context."""
        if not task_context or not context_affinity_json:
            return None
        try:
            affinity = json.loads(context_affinity_json)
            if not isinstance(affinity, dict) or not affinity:
                return None
        except (json.JSONDecodeError, TypeError):
            return None
        # Exact match.
        task_lower = task_context.lower().strip()
        for key, score in affinity.items():
            if task_lower in str(key).lower() or str(key).lower() in task_lower:
                return float(score)
        return None

    async def query_strategies(self, *, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search procedural skills by sqlite-vec and fall back to SQL LIKE."""
        await self.initialize()
        semantic = await self._semantic_query_strategies(query=query, limit=limit)
        if semantic:
            return semantic
        like_query = f"%{query}%"
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM procedural_skills
                WHERE skill_name LIKE ? OR COALESCE(optimized_prompt, '') LIKE ?
                ORDER BY success_rate DESC, updated_at DESC
                LIMIT ?
                """,
                (like_query, like_query, int(limit)),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def clear(self) -> int:
        """Delete all procedural skills."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM procedural_skills") as cursor:
                row = await cursor.fetchone()
                count = int(row[0]) if row else 0
            await db.execute("DELETE FROM procedural_skills")
            await db.execute(f"DELETE FROM {SKILL_CHUNKS_TABLE}")
            await db.execute(f"DELETE FROM {EXECUTION_TRACES_TABLE}")
            await db.execute("DELETE FROM l4_skills_fts")
            await db.commit()
        if self._vector_index is not None:
            await self._vector_index.clear()
        return count

    async def rebuild_embeddings(self, *, batch_size: int = 100) -> int:
        """Rebuild all persisted L4 skill embeddings from parent rows."""
        await self.initialize()
        normalized_batch_size = max(1, int(batch_size))
        if not self._vectors_enabled() or self._embedding_service is None or self._vector_index is None:
            return 0

        await self._vector_index.clear()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(f"DELETE FROM {SKILL_CHUNKS_TABLE}")
            await db.execute(
                """
                UPDATE procedural_skills
                SET embedding_status = ?, embedding_profile_id = NULL, embedding_chunk_count = 0, last_embedded_at = NULL
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
                    SELECT skill_id, skill_name, skill_category, optimized_prompt
                    FROM procedural_skills
                    ORDER BY updated_at DESC, skill_id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (normalized_batch_size, offset),
                ) as cursor:
                    rows = await cursor.fetchall()
            if not rows:
                break
            for row in rows:
                await self._maybe_upsert_skill_embedding(
                    skill_id=str(row["skill_id"]),
                    skill_name=str(row["skill_name"]),
                    skill_category=str(row["skill_category"]),
                    optimized_prompt=row["optimized_prompt"],
                )
            processed += len(rows)
            offset += len(rows)
        return processed

    async def bm25_search(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> List[Tuple[str, float]]:
        """Search L4 skills via FTS5 BM25 ranking.

        Returns a list of (skill_id, bm25_score) tuples ordered by relevance.
        """
        await self.initialize()
        tokenized = tokenize_for_fts(query)
        if not tokenized:
            return []
        escaped = escape_fts_query(tokenized)
        if not escaped:
            return []
        async with sqlite_connection_async(self.db_path) as db:
            try:
                async with db.execute(
                    """
                    SELECT skill_id, bm25(l4_skills_fts) AS score
                    FROM l4_skills_fts
                    WHERE l4_skills_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (escaped, limit),
                ) as cursor:
                    rows = await cursor.fetchall()
                return [(str(row[0]), float(row[1])) for row in rows]
            except Exception as exc:
                logger.warning("FTS5 BM25 search failed for L4 skills: %s", exc)
                return []

    async def backfill_fts(self, *, batch_size: int = 500) -> int:
        """Backfill FTS5 index from existing procedural_skills rows."""
        await self.initialize()
        indexed = 0
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT skill_id, skill_name, skill_category, optimized_prompt
                FROM procedural_skills
                WHERE skill_id NOT IN (SELECT skill_id FROM l4_skills_fts)
                """
            ) as cursor:
                batch: list[tuple[str, str]] = []
                async for row in cursor:
                    skill_id = str(row[0])
                    text = f"{row[1]} {row[2]} {row[3] or ''}"
                    batch.append((skill_id, tokenize_for_fts(text)))
                    if len(batch) >= batch_size:
                        await db.executemany(
                            "INSERT INTO l4_skills_fts(skill_id, content) VALUES (?, ?)",
                            batch,
                        )
                        indexed += len(batch)
                        batch.clear()
                if batch:
                    await db.executemany(
                        "INSERT INTO l4_skills_fts(skill_id, content) VALUES (?, ?)",
                        batch,
                    )
                    indexed += len(batch)
            await db.commit()
        return indexed

    def get_statistics(self) -> Dict[str, Any]:
        """Return lightweight metadata for higher-level reporting."""
        return {
            "db_path": self.db_path,
            "vector_enabled": self._vectors_enabled(),
            "async_embeddings": self._async_embeddings_enabled(),
            "embedding_queue_size": self._embedding_queue.qsize() if self._embedding_queue is not None else 0,
            "embedding_worker_running": bool(self._embedding_worker is not None and not self._embedding_worker.done()),
        }

    def _extract_skill_identity(
        self,
        event: MemoryEvent,
    ) -> Optional[Dict[str, Any]]:
        """Extract skill identity and trace data from a MemoryEvent.

        Returns a dict with keys:
            skill_name, skill_category, skill_type, success, duration_ms,
            error_summary, optimized_prompt, input_summary, output_summary,
            task_context
        """
        if event.event_type == "ActionExecuted":
            skill_name = str(event.source_item_id or event.content or "").strip()
            if not skill_name:
                return None
            meta = event.metadata_json or {}
            content_str = str(event.content or "").strip()
            optimized_prompt = content_str if content_str and content_str != skill_name else None
            success = int(event.level) < 3
            return {
                "skill_name": skill_name,
                "skill_category": "tool",
                "skill_type": "external_tool",
                "success": success,
                "duration_ms": float(meta.get("duration_ms", 0.0)),
                "error_summary": _truncate(meta.get("error"), 500) if not success else None,
                "optimized_prompt": optimized_prompt,
                "input_summary": _truncate(meta.get("input") or meta.get("params"), 500),
                "output_summary": _truncate(meta.get("output") or meta.get("result"), 500),
                "task_context": meta.get("task_category") or event.task_id,
            }

        if event.event_type == "TaskCompleted":
            skill_name = str(event.task_id or "task").strip()
            content_str = str(event.content or "").strip() or None
            return {
                "skill_name": skill_name,
                "skill_category": "workflow",
                "skill_type": "composite",
                "success": True,
                "duration_ms": 0.0,
                "error_summary": None,
                "optimized_prompt": content_str,
                "input_summary": None,
                "output_summary": _truncate(content_str, 500),
                "task_context": event.task_id,
            }

        if event.event_type == "TaskFailed":
            skill_name = str(event.task_id or "task").strip()
            content_str = str(event.content or "").strip() or None
            return {
                "skill_name": skill_name,
                "skill_category": "workflow",
                "skill_type": "composite",
                "success": False,
                "duration_ms": 0.0,
                "error_summary": _truncate(content_str, 500),
                "optimized_prompt": content_str,
                "input_summary": None,
                "output_summary": None,
                "task_context": event.task_id,
            }

        return None

    async def _insert_execution_trace(
        self,
        *,
        skill_id: str,
        event: MemoryEvent,
        identity: Dict[str, Any],
    ) -> None:
        """Insert a structured execution trace and prune old ones."""
        trace_id = f"trace_{uuid.uuid4().hex}"
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                f"""
                INSERT INTO {EXECUTION_TRACES_TABLE}(
                    trace_id, skill_id, event_id, success, duration_ms,
                    error_summary, input_summary, output_summary, task_context,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    skill_id,
                    event.event_id,
                    1 if identity["success"] else 0,
                    identity["duration_ms"],
                    identity.get("error_summary"),
                    identity.get("input_summary"),
                    identity.get("output_summary"),
                    identity.get("task_context"),
                    now,
                ),
            )
            await db.commit()
        await self._prune_old_traces(skill_id)

    async def _prune_old_traces(self, skill_id: str) -> None:
        """Keep at most MAX_TRACES_PER_SKILL traces per skill."""
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                f"""
                DELETE FROM {EXECUTION_TRACES_TABLE}
                WHERE skill_id = ? AND trace_id NOT IN (
                    SELECT trace_id FROM {EXECUTION_TRACES_TABLE}
                    WHERE skill_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                )
                """,
                (skill_id, skill_id, MAX_TRACES_PER_SKILL),
            )
            await db.commit()

    async def get_recent_traces(
        self,
        skill_id: str,
        *,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Return the most recent execution traces for a skill."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT trace_id, skill_id, event_id, success, duration_ms,
                       error_summary, input_summary, output_summary, task_context,
                       created_at
                FROM {EXECUTION_TRACES_TABLE}
                WHERE skill_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (skill_id, int(limit)),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            {
                "trace_id": str(row["trace_id"]),
                "skill_id": str(row["skill_id"]),
                "event_id": str(row["event_id"]),
                "success": bool(row["success"]),
                "duration_ms": float(row["duration_ms"] or 0.0),
                "error_summary": row["error_summary"],
                "input_summary": row["input_summary"],
                "output_summary": row["output_summary"],
                "task_context": row["task_context"],
                "created_at": float(row["created_at"]),
            }
            for row in rows
        ]

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
        if self._strategy_extractor is None:
            return
        traces = await self.get_recent_traces(skill_id, limit=20)
        if not traces:
            return
        strategy = await self._strategy_extractor.extract_strategy(
            skill_name=skill_name,
            skill_category=skill_category,
            total_attempts=total_attempts,
            success_rate=success_rate,
            traces=traces,
        )
        if strategy is None:
            return
        await self._persist_strategy(
            skill_id=skill_id,
            strategy=strategy,
        )

    async def _persist_strategy(
        self,
        *,
        skill_id: str,
        strategy: ExtractedStrategy,
    ) -> None:
        """Write extracted strategy to the procedural_skills row and reset pending count."""
        now = time.time()
        strategy_json = strategy.to_json()
        context_affinity_json = json.dumps(strategy.context_preferences, ensure_ascii=False)
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                UPDATE procedural_skills
                SET optimized_prompt = ?,
                    context_affinity = ?,
                    optimization_score = ?,
                    pending_trace_count = 0,
                    updated_at = ?
                WHERE skill_id = ?
                """,
                (
                    strategy_json,
                    context_affinity_json,
                    strategy.confidence,
                    now,
                    skill_id,
                ),
            )
            await db.commit()
        logger.info(
            "L4 strategy persisted for skill %s (confidence=%.2f)",
            skill_id,
            strategy.confidence,
        )

    def _rolling_average(self, current_value: Any, current_count: int, next_value: float) -> float:
        current = float(current_value or 0.0)
        if current_count <= 0:
            return next_value
        return ((current * current_count) + next_value) / (current_count + 1)

    def _row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        return {
            "skill_id": str(row["skill_id"]),
            "skill_name": str(row["skill_name"]),
            "skill_category": str(row["skill_category"]),
            "skill_type": str(row["skill_type"]),
            "proficiency": float(row["proficiency"]),
            "total_attempts": int(row["total_attempts"]),
            "success_count": int(row["success_count"]),
            "failure_count": int(row["failure_count"]),
            "success_rate": float(row["success_rate"]),
            "avg_execution_time_ms": float(row["avg_execution_time_ms"] or 0.0),
            "min_execution_time_ms": float(row["min_execution_time_ms"] or 0.0),
            "max_execution_time_ms": float(row["max_execution_time_ms"] or 0.0),
            "p95_execution_time_ms": float(row["p95_execution_time_ms"] or 0.0),
            "circuit_breaker_state": str(row["circuit_breaker_state"]),
            "circuit_breaker_opened_at": float(row["circuit_breaker_opened_at"]) if row["circuit_breaker_opened_at"] else None,
            "circuit_breaker_failure_count": int(row["circuit_breaker_failure_count"]),
            "circuit_breaker_success_count": int(row["circuit_breaker_success_count"]),
            "optimized_prompt": row["optimized_prompt"],
            "optimized_params": json.loads(row["optimized_params"] or "{}"),
            "optimization_score": float(row["optimization_score"]) if row["optimization_score"] is not None else None,
            "context_affinity": json.loads(row["context_affinity"] or "{}"),
            "source_event_ids": json.loads(row["source_event_ids"] or "[]"),
            "last_used_at": float(row["last_used_at"]) if row["last_used_at"] else None,
            "last_success_at": float(row["last_success_at"]) if row["last_success_at"] else None,
            "last_failure_at": float(row["last_failure_at"]) if row["last_failure_at"] else None,
            "embedding_status": str(row["embedding_status"] or EMBEDDING_STATUS_DISABLED),
            "embedding_profile_id": row["embedding_profile_id"],
            "embedding_chunk_count": int(row["embedding_chunk_count"] or 0),
            "last_embedded_at": float(row["last_embedded_at"]) if row["last_embedded_at"] else None,
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "pending_trace_count": int(row["pending_trace_count"]) if row["pending_trace_count"] is not None else 0,
        }

    async def _maybe_upsert_skill_embedding(
        self,
        *,
        skill_id: str,
        skill_name: str,
        skill_category: str,
        optimized_prompt: Optional[str],
    ) -> None:
        if not self._vectors_enabled():
            return
        pipeline = self._build_embedding_pipeline()
        if pipeline is None:
            return
        text = self._build_skill_embedding_text(
            skill_name=skill_name,
            skill_category=skill_category,
            optimized_prompt=optimized_prompt,
        )
        results = await pipeline.upsert_items(
            [
                EmbeddingPipelineItem(
                    parent_id=skill_id,
                    chunks=self._build_skill_embedding_chunks(
                        skill_id=skill_id,
                        text=text,
                    ),
                    metadata={
                        "skill_id": skill_id,
                        "skill_name": skill_name,
                        "skill_category": skill_category,
                    },
                    payload={
                        "skill_id": skill_id,
                    },
                )
            ]
        )
        if not results:
            return
        result = results[0]
        profile = self._profile_from_embedding_result(result.embeddings[0])
        await self._replace_skill_chunks(skill_id=skill_id, chunks=result.chunks, embedded_at=result.embedded_at)
        await self._update_skill_embedding_state(
            skill_id=skill_id,
            status=EMBEDDING_STATUS_READY,
            profile_id=profile.profile_id,
            chunk_count=len(result.chunks),
            embedded_at=result.embedded_at,
        )

    def _build_embedding_pipeline(self) -> MemoryEmbeddingPipeline | None:
        if self._embedding_service is None or self._vector_index is None:
            return None
        return MemoryEmbeddingPipeline(
            embedding_service=self._embedding_service,
            vector_index=self._vector_index,
        )

    async def _semantic_query_strategies(self, *, query: str, limit: int) -> List[Dict[str, Any]]:
        if not self._vectors_enabled() or self._embedding_service is None or self._vector_index is None or not query.strip():
            return []
        embedding = await self._embedding_service.embed_text(query)
        if embedding is None:
            return []
        try:
            hits = await self._vector_index.search(embedding=embedding, limit=max(limit * 3, 10))
        except Exception as exc:
            logger.warning("Failed semantic search over procedural skills: %s", exc)
            return []
        if not hits:
            return []
        skill_ids, matched_chunks = await self._fold_skill_chunk_hits(hits)
        if not skill_ids:
            return []
        placeholders = ", ".join("?" for _ in skill_ids)
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM procedural_skills WHERE skill_id IN ({placeholders})",
                tuple(skill_ids),
            ) as cursor:
                rows = await cursor.fetchall()
        skills_by_id = {str(row["skill_id"]): self._row_to_dict(row) for row in rows}
        ranked: List[Dict[str, Any]] = []
        for skill_id in skill_ids:
            skill = skills_by_id.get(skill_id)
            if skill is None:
                continue
            skill["matched_chunks"] = matched_chunks.get(skill_id, [])
            if skill["matched_chunks"]:
                skill["distance"] = float(skill["matched_chunks"][0]["distance"])
            ranked.append(skill)
            if len(ranked) >= limit:
                break
        return ranked

    def _build_skill_embedding_text(
        self,
        *,
        skill_name: str,
        skill_category: str,
        optimized_prompt: Optional[str],
    ) -> str:
        return build_l4_embedding_text(
            skill_name=skill_name,
            skill_category=skill_category,
            optimized_prompt=optimized_prompt,
        )

    async def _schedule_skill_embedding(
        self,
        *,
        skill_id: str,
        skill_name: str,
        skill_category: str,
        optimized_prompt: Optional[str],
    ) -> None:
        if not self._vectors_enabled():
            return
        if self._embedding_queue is not None and self._async_embeddings_enabled():
            await self._embedding_queue.put(
                {
                    "skill_id": skill_id,
                    "skill_name": skill_name,
                    "skill_category": skill_category,
                    "optimized_prompt": optimized_prompt,
                }
            )
            return
        await self._maybe_upsert_skill_embedding(
            skill_id=skill_id,
            skill_name=skill_name,
            skill_category=skill_category,
            optimized_prompt=optimized_prompt,
        )

    async def _run_embedding_worker(self) -> None:
        if self._embedding_queue is None:
            return
        while True:
            item = await self._embedding_queue.get()
            if item is None:
                self._embedding_queue.task_done()
                break
            try:
                await self._maybe_upsert_skill_embedding(
                    skill_id=str(item["skill_id"]),
                    skill_name=str(item["skill_name"]),
                    skill_category=str(item["skill_category"]),
                    optimized_prompt=item.get("optimized_prompt"),
                )
            finally:
                self._embedding_queue.task_done()

    def _build_skill_embedding_chunks(self, *, skill_id: str, text: str) -> list[ChunkedText]:
        chunks = chunk_text(text)
        return [
            ChunkedText(
                chunk_id=self._chunk_id_for_skill(skill_id, chunk.chunk_index),
                text=chunk.text,
                chunk_index=chunk.chunk_index,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                token_estimate=chunk.token_estimate,
            )
            for chunk in chunks
        ]

    def _chunk_id_for_skill(self, skill_id: str, chunk_index: int) -> str:
        return f"{skill_id}::chunk-{chunk_index}"

    async def _replace_skill_chunks(self, *, skill_id: str, chunks: list[ChunkedText], embedded_at: float) -> None:
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                f"DELETE FROM {SKILL_CHUNKS_TABLE} WHERE skill_id = ?",
                (skill_id,),
            )
            await db.executemany(
                f"""
                INSERT INTO {SKILL_CHUNKS_TABLE}(
                    chunk_id, skill_id, chunk_index, chunk_text, char_start, char_end,
                    token_estimate, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.chunk_id,
                        skill_id,
                        chunk.chunk_index,
                        chunk.text,
                        chunk.char_start,
                        chunk.char_end,
                        chunk.token_estimate,
                        embedded_at,
                        embedded_at,
                    )
                    for chunk in chunks
                ],
            )
            await db.commit()

    async def _update_skill_embedding_state(
        self,
        *,
        skill_id: str,
        status: str,
        profile_id: str | None,
        chunk_count: int,
        embedded_at: float,
    ) -> None:
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                UPDATE procedural_skills
                SET embedding_status = ?, embedding_profile_id = ?, embedding_chunk_count = ?, last_embedded_at = ?, updated_at = updated_at
                WHERE skill_id = ?
                """,
                (status, profile_id, int(chunk_count), float(embedded_at), skill_id),
            )
            await db.commit()

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

    async def _fetch_skill_chunk_rows_by_ids(self, chunk_ids: list[str]) -> list[aiosqlite.Row]:
        if not chunk_ids:
            return []
        placeholders = ", ".join("?" for _ in chunk_ids)
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT chunk_id, skill_id, chunk_index, chunk_text, char_start, char_end
                FROM {SKILL_CHUNKS_TABLE}
                WHERE chunk_id IN ({placeholders})
                """,
                tuple(chunk_ids),
            ) as cursor:
                return await cursor.fetchall()

    async def _fold_skill_chunk_hits(
        self,
        hits: list[VectorSearchHit],
    ) -> tuple[list[str], dict[str, list[dict[str, Any]]]]:
        chunk_ids = [hit.entity_id for hit in hits]
        chunk_rows = await self._fetch_skill_chunk_rows_by_ids(chunk_ids)
        chunk_by_id = {str(row["chunk_id"]): row for row in chunk_rows}
        skill_ids: list[str] = []
        matched_chunks: dict[str, list[dict[str, Any]]] = {}
        for hit in hits:
            row = chunk_by_id.get(hit.entity_id)
            if row is None:
                continue
            skill_id = str(row["skill_id"])
            if skill_id not in matched_chunks:
                skill_ids.append(skill_id)
                matched_chunks[skill_id] = []
            matched_chunks[skill_id].append(
                {
                    "chunk_id": str(row["chunk_id"]),
                    "chunk_index": int(row["chunk_index"]),
                    "text": str(row["chunk_text"]),
                    "char_start": int(row["char_start"]),
                    "char_end": int(row["char_end"]),
                    "distance": float(hit.distance),
                }
            )
        return skill_ids, matched_chunks


__all__ = ["L4ProceduralMemoryStore"]
