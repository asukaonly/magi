"""L3 reflection memory store."""

from __future__ import annotations

import json
import logging
import asyncio
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import aiosqlite

from ...llm import ScenarioLLMPool
from ..embedding_service import MemoryEmbeddingService
from ..hybrid_retrieval.fts_utils import escape_fts_query, tokenize_for_fts
from ..l1.event_store import L1EventStore
from ..sqlite_vec_index import SqliteVecIndex
from .models import L3Candidate
from .temporal_llm_service import TemporalSummaryLLMService
from .validator import validate_candidate

if TYPE_CHECKING:
    from .models import L3Candidate

logger = logging.getLogger(__name__)


class L3SummaryStore:
    """Stores reflection-oriented summaries that remain traceable to L1 evidence."""

    def __init__(
        self,
        *,
        db_path: str = "~/.magi/data/memories/memory.db",
        embedding_service: MemoryEmbeddingService | None = None,
        vector_enabled: bool = True,
        async_embeddings: bool = True,
        enable_temporal_llm_summary: bool = True,
        temporal_llm_timeout_seconds: float = 3.0,
        temporal_llm_min_event_count: int = 2,
        scenario_llm_pool: ScenarioLLMPool | None = None,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._embedding_service = embedding_service
        self._vector_enabled = bool(vector_enabled and embedding_service is not None)
        self._async_embeddings = bool(async_embeddings)
        self._temporal_llm_service = TemporalSummaryLLMService(
            enabled=enable_temporal_llm_summary,
            llm_timeout_seconds=temporal_llm_timeout_seconds,
            min_event_count_for_llm=temporal_llm_min_event_count,
            scenario_llm_pool=scenario_llm_pool,
        )
        self._vector_index = (
            SqliteVecIndex(
                db_path=self.db_path,
                registry_table="l3_summary_vectors",
                entity_column="summary_id",
                vec_table_prefix="l3_summary_vec",
            )
            if self._vector_enabled
            else None
        )
        self._embedding_queue: asyncio.Queue[Dict[str, Any] | None] | None = asyncio.Queue() if self._vector_enabled and self._async_embeddings else None
        self._embedding_worker: asyncio.Task[None] | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Create the summaries schema."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS summaries (
                    summary_id TEXT PRIMARY KEY,
                    summary_type TEXT NOT NULL,
                    summary_category TEXT NOT NULL,
                    period_start REAL NOT NULL,
                    period_end REAL NOT NULL,
                    content TEXT NOT NULL,
                    key_topics TEXT,
                    key_entities TEXT,
                    sentiment_summary TEXT,
                    change_and_pattern TEXT,
                    source_event_ids TEXT NOT NULL,
                    source_event_count INTEGER NOT NULL,
                    importance_aggregate REAL,
                    event_type_distribution TEXT,
                    generated_by_model TEXT,
                    generation_prompt TEXT,
                    generation_reason TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_summaries_period ON summaries(summary_type, summary_category, period_start, period_end);

                CREATE TABLE IF NOT EXISTS summary_event_links (
                    link_id TEXT PRIMARY KEY,
                    summary_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    link_role TEXT NOT NULL,
                    evidence_weight REAL NOT NULL DEFAULT 1.0,
                    created_at REAL NOT NULL,
                    UNIQUE(summary_id, event_id, link_role)
                );
                CREATE INDEX IF NOT EXISTS idx_summary_event_links_summary ON summary_event_links(summary_id);
                CREATE INDEX IF NOT EXISTS idx_summary_event_links_event ON summary_event_links(event_id);

                CREATE TABLE IF NOT EXISTS summary_task_links (
                    link_id TEXT PRIMARY KEY,
                    summary_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    link_role TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(summary_id, task_id, link_role)
                );
                CREATE INDEX IF NOT EXISTS idx_summary_task_links_summary ON summary_task_links(summary_id);
                CREATE INDEX IF NOT EXISTS idx_summary_task_links_task ON summary_task_links(task_id);

                CREATE TABLE IF NOT EXISTS l3_summary_vectors (
                    vec_rowid INTEGER PRIMARY KEY,
                    summary_id TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding_dim INTEGER NOT NULL,
                    vec_table TEXT NOT NULL,
                    metadata TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(summary_id, embedding_model)
                );
                CREATE INDEX IF NOT EXISTS idx_l3_summary_vectors_summary ON l3_summary_vectors(summary_id);
                CREATE INDEX IF NOT EXISTS idx_l3_summary_vectors_model ON l3_summary_vectors(embedding_model);

                CREATE VIRTUAL TABLE IF NOT EXISTS l3_summaries_fts USING fts5(
                    summary_id UNINDEXED,
                    content,
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

    async def generate_temporal_summary(
        self,
        *,
        l1_store: L1EventStore,
        summary_category: str,
        period_start: float,
        period_end: float,
    ) -> Optional[Dict[str, Any]]:
        """Build a temporal summary from eligible L1 events."""
        await self.initialize()
        candidates = await l1_store.query_events(
            start_time=period_start,
            end_time=period_end,
            cognition_eligible=True,
            limit=500,
        )
        events = [
            event
            for event in candidates
            if event["memory_domain"] != "runtime_telemetry" and event["retention_class"] != "disposable"
        ]
        if not events:
            return None

        evidence_pack = self._temporal_llm_service.build_evidence_pack(
            events=events,
            summary_category=summary_category,
            period_start=period_start,
            period_end=period_end,
        )
        if not evidence_pack.source_event_ids:
            return None

        fallback_summary = " ".join(event["raw_content"] for event in events[:6]).strip()
        generation = await self._temporal_llm_service.generate_temporal_candidate(
            evidence_pack,
            fallback_summary=fallback_summary,
        )
        decision = validate_candidate(generation.candidate, evidence_events=events)
        if decision.action != "accept" and not generation.used_fallback:
            generation = self._temporal_llm_service._build_fallback_result(
                evidence_pack,
                fallback_summary,
            )
            decision = validate_candidate(generation.candidate, evidence_events=events)
        if decision.action != "accept":
            return None
        summary_overrides: dict[str, Any] = {
            "summary_id": f"summary_{uuid.uuid4().hex}",
            "summary_type": "temporal",
            "summary_category": summary_category,
            "period_start": float(period_start),
            "period_end": float(period_end),
            "key_topics": [],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
            "source_event_ids": list(evidence_pack.source_event_ids),
            "source_event_count": int(evidence_pack.source_event_count),
            "importance_aggregate": evidence_pack.importance_aggregate or 0.0,
            "event_type_distribution": dict(evidence_pack.event_type_distribution),
            "generated_by_model": "rule-summary" if generation.used_fallback else "temporal-llm",
            "generation_prompt": None,
            "generation_reason": f"temporal:{summary_category}",
        }
        summary_overrides.update(generation.summary_overrides)
        summary = await self.upsert_candidate(
            candidate=generation.candidate,
            summary_overrides=summary_overrides,
        )
        return summary

    async def search_summaries(
        self,
        *,
        query: str,
        summary_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search summaries using sqlite-vec and fall back to keyword matching."""
        await self.initialize()
        semantic = await self._semantic_search_summaries(query=query, summary_type=summary_type, limit=limit)
        if semantic:
            return semantic
        sql = "SELECT * FROM summaries WHERE content LIKE ?"
        args: List[Any] = [f"%{query}%"]
        if summary_type:
            sql += " AND summary_type = ?"
            args.append(summary_type)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(int(limit))
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def list_summaries(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        """List most recent summaries."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM summaries ORDER BY updated_at DESC LIMIT ?", (int(limit),)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def clear(self) -> int:
        """Delete all summaries."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM summaries") as cursor:
                row = await cursor.fetchone()
                count = int(row[0]) if row else 0
            await db.execute("DELETE FROM summary_event_links")
            await db.execute("DELETE FROM summary_task_links")
            await db.execute("DELETE FROM summaries")
            await db.execute("DELETE FROM l3_summaries_fts")
            await db.commit()
        if self._vector_index is not None:
            await self._vector_index.clear()
        return count

    async def upsert_candidate(
        self,
        *,
        candidate: "L3Candidate",
        source_task_ids: Optional[list[str]] = None,
        summary_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist a structured L3 candidate and its evidence links."""
        await self.initialize()
        now = time.time()
        summary = {
            "summary_id": f"summary_{uuid.uuid4().hex}",
            "summary_type": str(candidate.summary_type),
            "summary_category": str(candidate.summary_category),
            "period_start": now,
            "period_end": now,
            "content": candidate.content,
            "key_topics": [],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
            "source_event_ids": list(candidate.source_event_ids),
            "source_event_count": len(candidate.source_event_ids),
            "importance_aggregate": 0.0,
            "event_type_distribution": {},
            "generated_by_model": "rule-summary",
            "generation_prompt": None,
            "generation_reason": f"{candidate.summary_type}:{candidate.summary_category}",
            "created_at": now,
            "updated_at": now,
        }
        if summary_overrides:
            summary.update(summary_overrides)
        summary.setdefault("summary_id", f"summary_{uuid.uuid4().hex}")
        summary.setdefault("created_at", now)
        summary["updated_at"] = float(summary.get("updated_at") or now)
        await self._store_summary(summary)
        await self._replace_summary_event_links(summary["summary_id"], candidate.source_event_ids)
        await self._replace_summary_task_links(summary["summary_id"], source_task_ids or [])
        return summary

    async def list_summary_event_links(self, summary_id: str) -> List[Dict[str, Any]]:
        """Return event links for a summary."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT link_id, summary_id, event_id, link_role, evidence_weight, created_at
                FROM summary_event_links
                WHERE summary_id = ?
                ORDER BY created_at ASC
                """,
                (summary_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            {
                "link_id": str(row["link_id"]),
                "summary_id": str(row["summary_id"]),
                "event_id": str(row["event_id"]),
                "link_role": str(row["link_role"]),
                "evidence_weight": float(row["evidence_weight"]),
                "created_at": float(row["created_at"]),
            }
            for row in rows
        ]

    async def list_summary_task_links(self, summary_id: str) -> List[Dict[str, Any]]:
        """Return task links for a summary."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT link_id, summary_id, task_id, link_role, created_at
                FROM summary_task_links
                WHERE summary_id = ?
                ORDER BY created_at ASC
                """,
                (summary_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            {
                "link_id": str(row["link_id"]),
                "summary_id": str(row["summary_id"]),
                "task_id": str(row["task_id"]),
                "link_role": str(row["link_role"]),
                "created_at": float(row["created_at"]),
            }
            for row in rows
        ]

    async def bm25_search(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> List[Tuple[str, float]]:
        """Search L3 summaries via FTS5 BM25 ranking.

        Returns a list of (summary_id, bm25_score) tuples ordered by relevance.
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
                    SELECT summary_id, bm25(l3_summaries_fts) AS score
                    FROM l3_summaries_fts
                    WHERE l3_summaries_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (escaped, limit),
                ) as cursor:
                    rows = await cursor.fetchall()
                return [(str(row[0]), float(row[1])) for row in rows]
            except Exception as exc:
                logger.warning("FTS5 BM25 search failed for L3 summaries: %s", exc)
                return []

    async def backfill_fts(self, *, batch_size: int = 500) -> int:
        """Backfill FTS5 index from existing summaries rows."""
        await self.initialize()
        indexed = 0
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT summary_id, content FROM summaries
                WHERE summary_id NOT IN (SELECT summary_id FROM l3_summaries_fts)
                """
            ) as cursor:
                batch: list[tuple[str, str]] = []
                async for row in cursor:
                    summary_id = str(row[0])
                    raw = str(row[1])
                    batch.append((summary_id, tokenize_for_fts(raw)))
                    if len(batch) >= batch_size:
                        await db.executemany(
                            "INSERT INTO l3_summaries_fts(summary_id, content) VALUES (?, ?)",
                            batch,
                        )
                        indexed += len(batch)
                        batch.clear()
                if batch:
                    await db.executemany(
                        "INSERT INTO l3_summaries_fts(summary_id, content) VALUES (?, ?)",
                        batch,
                    )
                    indexed += len(batch)
            await db.commit()
        return indexed

    def get_statistics(self) -> Dict[str, Any]:
        """Return lightweight metadata for reporting."""
        return {"db_path": self.db_path}

    async def _store_summary(self, summary: Dict[str, Any]) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO summaries(
                    summary_id, summary_type, summary_category, period_start, period_end,
                    content, key_topics, key_entities, sentiment_summary, change_and_pattern, source_event_ids,
                    source_event_count, importance_aggregate, event_type_distribution,
                    generated_by_model, generation_prompt, generation_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary["summary_id"],
                    summary["summary_type"],
                    summary["summary_category"],
                    float(summary["period_start"]),
                    float(summary["period_end"]),
                    summary["content"],
                    json.dumps(summary["key_topics"], ensure_ascii=False),
                    json.dumps(summary["key_entities"], ensure_ascii=False),
                    self._encode_optional_json(summary["sentiment_summary"]),
                    self._encode_optional_json(summary.get("change_and_pattern")),
                    json.dumps(summary["source_event_ids"], ensure_ascii=False),
                    int(summary["source_event_count"]),
                    float(summary["importance_aggregate"]),
                    json.dumps(summary["event_type_distribution"], ensure_ascii=False),
                    summary["generated_by_model"],
                    summary["generation_prompt"],
                    summary["generation_reason"],
                    float(summary["created_at"]),
                    float(summary["updated_at"]),
                ),
            )
            # Sync FTS5 index
            tokenized = tokenize_for_fts(summary["content"])
            await db.execute(
                "DELETE FROM l3_summaries_fts WHERE summary_id = ?",
                (summary["summary_id"],),
            )
            await db.execute(
                "INSERT INTO l3_summaries_fts(summary_id, content) VALUES (?, ?)",
                (summary["summary_id"], tokenized),
            )
            await db.commit()
        await self._schedule_summary_embedding(summary)

    async def _replace_summary_event_links(self, summary_id: str, event_ids: list[str]) -> None:
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM summary_event_links WHERE summary_id = ?", (summary_id,))
            if event_ids:
                await db.executemany(
                    """
                    INSERT INTO summary_event_links(
                        link_id, summary_id, event_id, link_role, evidence_weight, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (f"sel_{uuid.uuid4().hex}", summary_id, event_id, "primary", 1.0, now)
                        for event_id in event_ids
                    ],
                )
            await db.commit()

    async def _replace_summary_task_links(self, summary_id: str, task_ids: list[str]) -> None:
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM summary_task_links WHERE summary_id = ?", (summary_id,))
            if task_ids:
                await db.executemany(
                    """
                    INSERT INTO summary_task_links(
                        link_id, summary_id, task_id, link_role, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (f"stl_{uuid.uuid4().hex}", summary_id, task_id, "source_task", now)
                        for task_id in task_ids
                    ],
                )
            await db.commit()

    def _row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        return {
            "summary_id": str(row["summary_id"]),
            "summary_type": str(row["summary_type"]),
            "summary_category": str(row["summary_category"]),
            "period_start": float(row["period_start"]),
            "period_end": float(row["period_end"]),
            "content": str(row["content"]),
            "key_topics": json.loads(row["key_topics"] or "[]"),
            "key_entities": json.loads(row["key_entities"] or "[]"),
            "sentiment_summary": self._decode_optional_json(row["sentiment_summary"]),
            "change_and_pattern": self._decode_optional_json(row["change_and_pattern"]),
            "source_event_ids": json.loads(row["source_event_ids"] or "[]"),
            "source_event_count": int(row["source_event_count"]),
            "importance_aggregate": float(row["importance_aggregate"] or 0.0),
            "event_type_distribution": json.loads(row["event_type_distribution"] or "{}"),
            "generated_by_model": row["generated_by_model"],
            "generation_prompt": row["generation_prompt"],
            "generation_reason": row["generation_reason"],
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def _encode_optional_json(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _decode_optional_json(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    async def _maybe_upsert_summary_embedding(self, summary: Dict[str, Any]) -> None:
        if not self._vector_enabled or self._embedding_service is None or self._vector_index is None:
            return
        embedding = await self._embedding_service.embed_text(str(summary.get("content") or ""))
        if embedding is None:
            return
        try:
            await self._vector_index.upsert(
                entity_id=str(summary["summary_id"]),
                embedding=embedding,
                metadata={"summary_type": summary.get("summary_type"), "summary_category": summary.get("summary_category")},
            )
        except Exception as exc:
            logger.warning("Failed to upsert summary embedding for %s: %s", summary.get("summary_id"), exc)

    async def _semantic_search_summaries(
        self,
        *,
        query: str,
        summary_type: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        if not self._vector_enabled or self._embedding_service is None or self._vector_index is None or not query.strip():
            return []
        embedding = await self._embedding_service.embed_text(query)
        if embedding is None:
            return []
        try:
            hits = await self._vector_index.search(embedding=embedding, limit=max(limit * 3, 10))
        except Exception as exc:
            logger.warning("Failed semantic search over summaries: %s", exc)
            return []
        if not hits:
            return []
        summary_ids = [hit.entity_id for hit in hits]
        placeholders = ", ".join("?" for _ in summary_ids)
        sql = f"SELECT * FROM summaries WHERE summary_id IN ({placeholders})"
        args: List[Any] = list(summary_ids)
        if summary_type:
            sql += " AND summary_type = ?"
            args.append(summary_type)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        summaries_by_id = {str(row["summary_id"]): self._row_to_dict(row) for row in rows}
        ranked: List[Dict[str, Any]] = []
        for hit in hits:
            summary = summaries_by_id.get(hit.entity_id)
            if summary is None:
                continue
            summary["distance"] = hit.distance
            ranked.append(summary)
            if len(ranked) >= limit:
                break
        return ranked

    async def _schedule_summary_embedding(self, summary: Dict[str, Any]) -> None:
        if not self._vector_enabled:
            return
        if self._embedding_queue is not None:
            await self._embedding_queue.put(dict(summary))
            return
        await self._maybe_upsert_summary_embedding(summary)

    async def _run_embedding_worker(self) -> None:
        if self._embedding_queue is None:
            return
        while True:
            item = await self._embedding_queue.get()
            if item is None:
                self._embedding_queue.task_done()
                break
            try:
                await self._maybe_upsert_summary_embedding(item)
            finally:
                self._embedding_queue.task_done()


__all__ = ["L3SummaryStore"]
