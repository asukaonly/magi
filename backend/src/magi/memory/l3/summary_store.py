"""L3 reflection memory store."""

from __future__ import annotations

import logging
import asyncio
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ...config.models import EmbeddingBackend
from ...llm import ScenarioLLMPool
from ..embedding.embedding_service import MemoryEmbeddingService
from ..l1.event_store import L1EventStore
from ..embedding.sqlite_vec_index import SqliteVecIndex
from .evidence_selector import select_temporal_evidence
from .episodic_service import EpisodicSummaryLLMService
from .topic_llm_service import TopicSummaryLLMService
from .temporal_llm_service import TemporalSummaryLLMService
from .validator import validate_candidate
from .embeddings.operations import L3SummaryEmbeddingMixin
from .retrieval.operations import L3SummarySearchMixin
from .storage.schema import ensure_l3_summary_schema
from .storage.operations import L3SummaryPersistenceMixin
from .storage.review_operations import L3ReviewOperationsMixin

logger = logging.getLogger(__name__)

_PREVIOUS_PERIOD_CONTEXT_LIMITS = {
    "hour": 1,
    "day": 1,
    "week": 3,
    "month": 3,
    "quarter": 2,
    "year": 2,
}
_CHILD_PERIOD_CONTEXT_CATEGORIES = {
    "day": ["hour"],
    "week": ["day"],
    "month": ["week"],
    "quarter": ["month"],
    "year": ["quarter"],
}
_CHILD_PERIOD_CONTEXT_LIMIT_BY_PARENT = {
    "day": 24,
    "week": 8,
    "month": 6,
    "quarter": 4,
    "year": 5,
}
_CHILD_PERIOD_CONTEXT_LIMIT_DEFAULT = 6

class L3SummaryStore(L3SummaryEmbeddingMixin, L3SummarySearchMixin, L3SummaryPersistenceMixin, L3ReviewOperationsMixin):
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
        self._episodic_llm_service = EpisodicSummaryLLMService(
            enabled=True,
            llm_timeout_seconds=30.0,
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
            if self._vector_index is not None:
                await self._vector_index.initialize()
            await ensure_l3_summary_schema(db)
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
        await self._attach_temporal_summary_context(evidence_pack)

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

    async def _attach_temporal_summary_context(self, pack: Any) -> None:
        category = str(pack.summary_category)
        previous_limit = _PREVIOUS_PERIOD_CONTEXT_LIMITS.get(category, 0)
        if previous_limit:
            pack.previous_period_summaries = await self._list_previous_temporal_context(
                summary_category=category,
                before=float(pack.period_start),
                limit=previous_limit,
            )
        child_categories = _CHILD_PERIOD_CONTEXT_CATEGORIES.get(category, [])
        if child_categories:
            child_limit = _CHILD_PERIOD_CONTEXT_LIMIT_BY_PARENT.get(
                category, _CHILD_PERIOD_CONTEXT_LIMIT_DEFAULT
            )
            pack.child_period_summaries = await self._list_child_temporal_context(
                summary_categories=child_categories,
                period_start=float(pack.period_start),
                period_end=float(pack.period_end),
                limit=child_limit,
            )

    async def _list_previous_temporal_context(
        self,
        *,
        summary_category: str,
        before: float,
        limit: int,
    ) -> list[dict[str, object]]:
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM summaries
                WHERE summary_type = 'temporal'
                  AND summary_category = ?
                  AND period_end <= ?
                ORDER BY period_end DESC, updated_at DESC
                LIMIT ?
                """,
                (summary_category, float(before), int(limit)),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._summary_context_item(self._row_to_dict(row)) for row in rows]

    async def _list_child_temporal_context(
        self,
        *,
        summary_categories: list[str],
        period_start: float,
        period_end: float,
        limit: int,
    ) -> list[dict[str, object]]:
        normalized = [str(category).strip() for category in summary_categories if str(category).strip()]
        if not normalized:
            return []
        await self.initialize()
        placeholders = ", ".join("?" for _ in normalized)
        args: list[object] = [*normalized, float(period_start), float(period_end), int(limit)]
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT * FROM summaries
                WHERE summary_type = 'temporal'
                  AND summary_category IN ({placeholders})
                  AND period_end >= ?
                  AND period_start <= ?
                ORDER BY period_start ASC, period_end ASC, updated_at DESC
                LIMIT ?
                """,
                tuple(args),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._summary_context_item(self._row_to_dict(row)) for row in rows]

    def _summary_context_item(self, summary: dict[str, Any]) -> dict[str, object]:
        item: dict[str, object] = {
            "summary_id": str(summary.get("summary_id") or ""),
            "summary_category": str(summary.get("summary_category") or ""),
            "period_start": float(summary.get("period_start") or 0.0),
            "period_end": float(summary.get("period_end") or 0.0),
            "content": str(summary.get("content") or ""),
            "generated_by_model": str(summary.get("generated_by_model") or ""),
        }
        key_topics = summary.get("key_topics")
        if isinstance(key_topics, list) and key_topics:
            item["key_topics"] = [str(topic) for topic in key_topics[:6] if str(topic).strip()]
        change_and_pattern = summary.get("change_and_pattern")
        if isinstance(change_and_pattern, dict) and change_and_pattern:
            item["change_and_pattern"] = change_and_pattern
        return item

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

    async def generate_episodic_summary(
        self,
        *,
        l1_store: L1EventStore,
        episode: Dict[str, Any],
        episode_event_ids: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Build an L3 'episodic' thematic summary for one L2 episode.

        Args:
            l1_store: shared L1 event store to resolve event_id → row.
            episode: episode dict (must include episode_id, episode_type,
                time_start, time_end, primary_entity_ids, primary_topic_keys).
            episode_event_ids: list of L1 event IDs that belong to the episode
                (typically from l2.list_episode_events).
        """
        await self.initialize()
        episode_id = str(episode.get("episode_id") or "").strip()
        if not episode_id:
            return None
        if not episode_event_ids:
            return None

        # Resolve each event_id to its full L1 row. Skip missing.
        events: list[Dict[str, Any]] = []
        for event_id in episode_event_ids:
            row = await l1_store.get_event(event_id)
            if row is not None:
                events.append(row)
        if not events:
            return None

        pack = self._episodic_llm_service.build_episodic_evidence_pack(
            episode=episode,
            events=events,
        )

        # Build deterministic fallback strings.
        primary_entity_label = ", ".join(str(e) for e in pack.primary_entity_ids[:3]) or "活动"
        fallback_label = primary_entity_label[:16]
        snippets = [e.content for e in pack.events[:2] if e.content]
        joined = "；".join(snippets)
        fallback_content = (joined or f"持续 {len(pack.events)} 个事件的活动片段")[:200]

        generation = await self._episodic_llm_service.generate_episodic_candidate(
            pack,
            fallback_label=fallback_label,
            fallback_content=fallback_content,
        )

        summary = await self.upsert_candidate(
            candidate=generation.candidate,
            summary_overrides={
                "summary_id": f"summary_{uuid.uuid4().hex}",
                "summary_type": "thematic",
                "summary_category": "episodic",
                "period_start": pack.time_start,
                "period_end": pack.time_end,
            },
        )
        return summary

    def get_statistics(self) -> Dict[str, Any]:
        """Return lightweight metadata for reporting."""
        return {
            "db_path": self.db_path,
            "vector_enabled": self._vectors_enabled(),
            "async_embeddings": self._async_embeddings_enabled(),
            "embedding_queue_size": self._embedding_queue.qsize() if self._embedding_queue is not None else 0,
            "embedding_worker_running": bool(self._embedding_worker is not None and not self._embedding_worker.done()),
        }

__all__ = ["L3SummaryStore"]
