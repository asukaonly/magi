"""L3 reflection memory store."""

from __future__ import annotations

import json
import logging
import asyncio
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ...config.models import EmbeddingBackend
from ...llm import ScenarioLLMPool
from ..embedding.embedding_service import MemoryEmbeddingService
from ..hybrid_retrieval.fts_utils import tokenize_for_fts
from ..l1.event_store import L1EventStore
from ..embedding.sqlite_vec_index import SqliteVecIndex
from .evidence_selector import select_temporal_evidence
from .models import L3Candidate
from .topic_llm_service import TopicSummaryLLMService
from .temporal_llm_service import TemporalSummaryLLMService
from .validator import validate_candidate
from .embeddings.operations import L3SummaryEmbeddingMixin
from .retrieval.operations import L3SummarySearchMixin
from .storage.schema import (
    SUMMARY_CHUNKS_TABLE,
    ensure_summary_store_schema,
)
from .evidence.links import (
    build_summary_event_link_rows,
    build_summary_task_link_rows,
    normalize_event_ids,
    row_to_summary_event_link,
    row_to_summary_task_link,
)
from .storage.serialization import (
    decode_optional_json,
    encode_optional_json,
    row_to_summary_dict,
)

if TYPE_CHECKING:
    from .models import L3Candidate

logger = logging.getLogger(__name__)

class L3SummaryStore(L3SummaryEmbeddingMixin, L3SummarySearchMixin):
    """Stores reflection-oriented summaries that remain traceable to L1 evidence."""

    def __init__(
        self,
        *,
        db_path: str = "~/.magi/data/memory/memory.db",
        embedding_service: MemoryEmbeddingService | None = None,
        memory_config_getter: Callable[[], Any] | None = None,
        vector_enabled: bool = True,
        async_embeddings: bool = True,
        enable_temporal_llm_summary: bool = True,
        temporal_llm_timeout_seconds: float = 3.0,
        temporal_llm_min_event_count: int = 2,
        scenario_llm_pool: ScenarioLLMPool | None = None,
        temporal_summary_features_builder: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._embedding_service = embedding_service
        self._memory_config_getter = memory_config_getter
        self._default_vector_enabled = bool(vector_enabled and embedding_service is not None)
        self._default_async_embeddings = bool(async_embeddings)
        self._temporal_llm_service = TemporalSummaryLLMService(
            enabled=enable_temporal_llm_summary,
            llm_timeout_seconds=temporal_llm_timeout_seconds,
            min_event_count_for_llm=temporal_llm_min_event_count,
            scenario_llm_pool=scenario_llm_pool,
        )
        self._topic_llm_service = TopicSummaryLLMService(
            enabled=enable_temporal_llm_summary,
            llm_timeout_seconds=temporal_llm_timeout_seconds,
            scenario_llm_pool=scenario_llm_pool,
        )
        self._temporal_summary_features_builder = temporal_summary_features_builder
        self._vector_index = (
            SqliteVecIndex(
                db_path=self.db_path,
                registry_table="l3_summary_chunk_vectors",
                entity_column="chunk_id",
                vec_table_prefix="l3_summary_chunk_vec",
            )
            if embedding_service is not None or vector_enabled
            else None
        )
        self._embedding_queue: asyncio.Queue[Dict[str, Any] | None] | None = (
            asyncio.Queue() if embedding_service is not None else None
        )
        self._embedding_worker: asyncio.Task[None] | None = None
        self._embedding_batch_size = 5
        self._embedding_batch_wait_seconds = 1.0
        self._initialized = False

    async def initialize(self) -> None:
        """Create the summaries schema."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path) as db:
            await ensure_summary_store_schema(db)
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
            and config.l3.enabled
            and config.l3.vectors_enabled
        )

    def _async_embeddings_enabled(self) -> bool:
        config = self._current_memory_config()
        if config is None:
            return self._default_async_embeddings
        return bool(config.async_embeddings)

    async def generate_temporal_summary(
        self,
        *,
        l1_store: L1EventStore,
        summary_category: str,
        period_start: float,
        period_end: float,
        source_filter: Optional[List[str]] = None,
        min_events: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """Build a temporal summary from eligible L1 events."""
        await self.initialize()
        selection = await select_temporal_evidence(
            l1_store=l1_store,
            period_start=period_start,
            period_end=period_end,
            source_filter=list(source_filter) if source_filter else None,
        )
        events = list(selection.selected_events)
        if len(events) < max(1, int(min_events)):
            return None

        evidence_pack = self._temporal_llm_service.build_evidence_pack(
            events=events,
            summary_category=summary_category,
            period_start=period_start,
            period_end=period_end,
        )
        evidence_pack.window_event_count = int(selection.source_event_total)
        evidence_pack.omitted_event_count = int(selection.omitted_event_count)
        evidence_pack.source_distribution = dict(selection.source_distribution)
        evidence_pack.selection_policy = dict(selection.selection_policy)
        if self._temporal_summary_features_builder is not None:
            try:
                evidence_pack.plugin_summary_features = dict(
                    self._temporal_summary_features_builder(
                        events=list(selection.feature_events),
                        summary_category=summary_category,
                        period_start=period_start,
                        period_end=period_end,
                        source_filter=list(source_filter) if source_filter else None,
                        feature_budgets=dict(selection.feature_budgets),
                    )
                    or {}
                )
            except Exception as exc:
                logger.warning("L3 temporal summary features builder failed: %s", exc)
        if not evidence_pack.source_event_ids:
            return None

        fallback_summary = " ".join(event["content"] for event in events[:6]).strip()
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
            "evidence_selection": {
                "window_event_count": int(selection.source_event_total),
                "selected_event_count": int(evidence_pack.source_event_count),
                "omitted_event_count": int(selection.omitted_event_count),
                "source_distribution": dict(selection.source_distribution),
                "selection_policy": dict(selection.selection_policy),
            },
        }
        summary_overrides.update(generation.summary_overrides)
        summary = await self.upsert_candidate(
            candidate=generation.candidate,
            summary_overrides=summary_overrides,
        )
        return summary

    async def generate_thematic_summary(
        self,
        *,
        l1_store: L1EventStore,
        topic: str,
        period_start: float | None = None,
        period_end: float | None = None,
        min_source_count: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """Build a topic-oriented thematic summary from eligible L1 events."""
        await self.initialize()
        normalized_topic = str(topic).strip().lower()
        if not normalized_topic:
            return None

        candidates = await l1_store.query_events(
            start_time=period_start,
            end_time=period_end,
            cognition_eligible=True,
            limit=500,
        )
        topic_events = [
            event
            for event in candidates
            if event["memory_domain"] != "runtime_telemetry"
            and event["retention_class"] != "disposable"
            and normalized_topic in str(event.get("content") or "").lower()
        ]
        if len(topic_events) < max(1, int(min_source_count)):
            return None

        evidence_pack = self._topic_llm_service.build_evidence_pack(
            topic=topic,
            events=topic_events,
        )
        source_event_ids = list(evidence_pack.source_event_ids)
        snippets = [str(event.get("content") or "").strip() for event in topic_events[:4] if str(event.get("content") or "").strip()]
        fallback_summary = f"Topic '{topic}' recurred across {len(source_event_ids)} events. " + " ".join(snippets)
        fallback_summary = fallback_summary.strip()
        generation = await self._topic_llm_service.generate_topic_candidate(
            evidence_pack,
            fallback_summary=fallback_summary,
        )
        decision = validate_candidate(generation.candidate, evidence_events=topic_events)
        if decision.action != "accept" and not generation.used_fallback:
            generation = self._topic_llm_service._build_fallback_result(
                evidence_pack,
                fallback_summary,
            )
            decision = validate_candidate(generation.candidate, evidence_events=topic_events)
        if decision.action != "accept":
            return None

        timestamps = [float(event["timestamp"]) for event in topic_events if event.get("timestamp") is not None]
        summary = await self.upsert_candidate(
            candidate=generation.candidate,
            summary_overrides={
                "summary_id": f"summary_{uuid.uuid4().hex}",
                "summary_type": "thematic",
                "summary_category": "topic",
                "period_start": float(period_start) if period_start is not None else (min(timestamps) if timestamps else time.time()),
                "period_end": float(period_end) if period_end is not None else (max(timestamps) if timestamps else time.time()),
                "key_topics": [str(topic).strip()],
                "key_entities": [],
                "sentiment_summary": None,
                "change_and_pattern": None,
                "source_event_ids": source_event_ids,
                "source_event_count": len(source_event_ids),
                "importance_aggregate": evidence_pack.importance_aggregate or 0.0,
                "event_type_distribution": dict(evidence_pack.event_type_distribution),
                "generated_by_model": "rule-summary" if generation.used_fallback else "topic-llm",
                "generation_prompt": None,
                "generation_reason": f"thematic:topic:{normalized_topic}",
                **generation.summary_overrides,
            },
        )
        return summary

    async def count_summaries(self) -> int:
        """Count all summaries."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM summaries") as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def list_summaries(self, *, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List most recent summaries."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM summaries ORDER BY updated_at DESC LIMIT ? OFFSET ?", (int(limit), int(offset))) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def list_summaries_by_category(
        self,
        *,
        summary_categories: List[str],
        period_start: Optional[float] = None,
        period_end: Optional[float] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """List summaries scoped to one or more summary_category values within a window."""
        await self.initialize()
        normalized = [str(c).strip() for c in summary_categories if str(c).strip()]
        if not normalized:
            return []
        placeholders = ", ".join("?" for _ in normalized)
        sql = f"SELECT * FROM summaries WHERE summary_category IN ({placeholders})"
        args: List[Any] = list(normalized)
        if period_start is not None:
            sql += " AND period_end >= ?"
            args.append(float(period_start))
        if period_end is not None:
            sql += " AND period_start <= ?"
            args.append(float(period_end))
        sql += " ORDER BY period_end DESC, updated_at DESC LIMIT ?"
        args.append(int(limit))
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def clear(self) -> int:
        """Delete all summaries."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM summaries") as cursor:
                row = await cursor.fetchone()
                count = int(row[0]) if row else 0
            await db.execute("DELETE FROM summary_event_links")
            await db.execute("DELETE FROM summary_task_links")
            await db.execute("DELETE FROM summaries")
            await db.execute(f"DELETE FROM {SUMMARY_CHUNKS_TABLE}")
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
        async with sqlite_connection_async(self.db_path) as db:
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
        return [row_to_summary_event_link(row) for row in rows]

    async def list_summary_task_links(self, summary_id: str) -> List[Dict[str, Any]]:
        """Return task links for a summary."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
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
        return [row_to_summary_task_link(row) for row in rows]

    async def filter_linked_event_ids(self, event_ids: list[str]) -> list[str]:
        """Return the subset of event ids that are already covered by summary links."""
        await self.initialize()
        normalized_ids = normalize_event_ids(event_ids)
        if not normalized_ids:
            return []

        placeholders = ", ".join("?" for _ in normalized_ids)
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                f"""
                SELECT DISTINCT event_id
                FROM summary_event_links
                WHERE event_id IN ({placeholders})
                """,
                tuple(normalized_ids),
            ) as cursor:
                rows = await cursor.fetchall()
        covered = {str(row[0]) for row in rows}
        return [event_id for event_id in normalized_ids if event_id in covered]

    def get_statistics(self) -> Dict[str, Any]:
        """Return lightweight metadata for reporting."""
        return {
            "db_path": self.db_path,
            "vector_enabled": self._vectors_enabled(),
            "async_embeddings": self._async_embeddings_enabled(),
            "embedding_queue_size": self._embedding_queue.qsize() if self._embedding_queue is not None else 0,
            "embedding_worker_running": bool(self._embedding_worker is not None and not self._embedding_worker.done()),
        }

    async def _store_summary(self, summary: Dict[str, Any]) -> None:
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO summaries(
                    summary_id, summary_type, summary_category, period_start, period_end,
                    content, key_topics, key_entities, sentiment_summary, change_and_pattern, source_event_ids,
                    source_event_count, importance_aggregate, event_type_distribution,
                    generated_by_model, generation_prompt, generation_reason,
                    embedding_chunk_count, last_embedded_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    int(summary.get("embedding_chunk_count") or 0),
                    float(summary["last_embedded_at"]) if summary.get("last_embedded_at") is not None else None,
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
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("DELETE FROM summary_event_links WHERE summary_id = ?", (summary_id,))
            if event_ids:
                await db.executemany(
                    """
                    INSERT INTO summary_event_links(
                        link_id, summary_id, event_id, link_role, evidence_weight, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    build_summary_event_link_rows(
                        summary_id=summary_id,
                        event_ids=event_ids,
                        created_at=now,
                    ),
                )
            await db.commit()

    async def _replace_summary_task_links(self, summary_id: str, task_ids: list[str]) -> None:
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("DELETE FROM summary_task_links WHERE summary_id = ?", (summary_id,))
            if task_ids:
                await db.executemany(
                    """
                    INSERT INTO summary_task_links(
                        link_id, summary_id, task_id, link_role, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    build_summary_task_link_rows(
                        summary_id=summary_id,
                        task_ids=task_ids,
                        created_at=now,
                    ),
                )
            await db.commit()

    def _row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        return row_to_summary_dict(row)

    def _encode_optional_json(self, value: Any) -> str | None:
        return encode_optional_json(value)

    def _decode_optional_json(self, value: Any) -> Any:
        return decode_optional_json(value)

__all__ = ["L3SummaryStore"]
