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
from ..embedding_service import MemoryEmbeddingService
from ..event_contracts import MemoryEvent
from ..hybrid_retrieval.fts_utils import escape_fts_query, tokenize_for_fts
from ..sqlite_vec_index import SqliteVecIndex

logger = logging.getLogger(__name__)


class L4ProceduralMemoryStore:
    """Tracks procedural skills and breaker state from historical attempts."""

    def __init__(
        self,
        *,
        db_path: str = "~/.magi/data/memories/memory.db",
        embedding_service: MemoryEmbeddingService | None = None,
        memory_config_getter: Callable[[], Any] | None = None,
        vector_enabled: bool = True,
        async_embeddings: bool = True,
        breaker_failure_threshold: int = 3,
        breaker_recovery_successes: int = 2,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._embedding_service = embedding_service
        self._memory_config_getter = memory_config_getter
        self._default_vector_enabled = bool(vector_enabled and embedding_service is not None)
        self._default_async_embeddings = bool(async_embeddings)
        self._vector_index = (
            SqliteVecIndex(
                db_path=self.db_path,
                registry_table="l4_skill_vectors",
                entity_column="skill_id",
                vec_table_prefix="l4_skill_vec",
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
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(skill_name, skill_category)
                );
                CREATE INDEX IF NOT EXISTS idx_procedural_skill_name ON procedural_skills(skill_name, skill_category);

                CREATE TABLE IF NOT EXISTS l4_skill_vectors (
                    vec_rowid INTEGER PRIMARY KEY,
                    skill_id TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding_dim INTEGER NOT NULL,
                    vec_table TEXT NOT NULL,
                    metadata TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(skill_id, embedding_model)
                );
                CREATE INDEX IF NOT EXISTS idx_l4_skill_vectors_skill ON l4_skill_vectors(skill_id);
                CREATE INDEX IF NOT EXISTS idx_l4_skill_vectors_model ON l4_skill_vectors(embedding_model);

                CREATE VIRTUAL TABLE IF NOT EXISTS l4_skills_fts USING fts5(
                    skill_id UNINDEXED,
                    content,
                    tokenize='unicode61'
                );
                """
            )
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
        skill_name, skill_category, skill_type, success, duration_ms, error, optimized_prompt = identity
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
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    source_event_ids = ?, last_used_at = ?, last_success_at = ?, last_failure_at = ?, updated_at = ?
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

    async def get_all_skills(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        """List all stored skills."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM procedural_skills ORDER BY updated_at DESC LIMIT ?",
                (int(limit),),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

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
            await db.execute("DELETE FROM l4_skills_fts")
            await db.commit()
        if self._vector_index is not None:
            await self._vector_index.clear()
        return count

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
    ) -> Optional[tuple[str, str, str, bool, float, Optional[str], Optional[str]]]:
        if event.event_type == "ActionExecuted":
            skill_name = str(event.source_item_id or event.content or "").strip()
            if not skill_name:
                return None
            optimized_prompt = event.content if str(event.content or "").strip() and str(event.content).strip() != skill_name else None
            return (
                skill_name,
                "tool",
                "external_tool",
                int(event.level) < 3,
                0.0,
                None,
                optimized_prompt,
            )

        if event.event_type == "TaskCompleted":
            skill_name = str(event.task_id or "task").strip()
            return (
                skill_name,
                "workflow",
                "composite",
                True,
                0.0,
                None,
                str(event.content or "").strip() or None,
            )

        if event.event_type == "TaskFailed":
            skill_name = str(event.task_id or "task").strip()
            return (
                skill_name,
                "workflow",
                "composite",
                False,
                0.0,
                None,
                str(event.content or "").strip() or None,
            )

        return None

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
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    async def _maybe_upsert_skill_embedding(
        self,
        *,
        skill_id: str,
        skill_name: str,
        skill_category: str,
        optimized_prompt: Optional[str],
    ) -> None:
        if not self._vectors_enabled() or self._embedding_service is None or self._vector_index is None:
            return
        text = self._build_skill_embedding_text(
            skill_name=skill_name,
            skill_category=skill_category,
            optimized_prompt=optimized_prompt,
        )
        embedding = await self._embedding_service.embed_text(text)
        if embedding is None:
            return
        try:
            await self._vector_index.upsert(
                entity_id=skill_id,
                embedding=embedding,
                metadata={"skill_name": skill_name, "skill_category": skill_category},
            )
        except Exception as exc:
            logger.warning("Failed to upsert skill embedding for %s: %s", skill_id, exc)

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
        skill_ids = [hit.entity_id for hit in hits]
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
        for hit in hits:
            skill = skills_by_id.get(hit.entity_id)
            if skill is None:
                continue
            skill["distance"] = hit.distance
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
        parts = [skill_name, skill_category]
        if optimized_prompt:
            parts.append(optimized_prompt)
        return "\n".join(part for part in parts if part)

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


__all__ = ["L4ProceduralMemoryStore"]
