"""Unified entrypoints for the rewritten L0-L4 memory system."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any, Callable, Dict, Optional

from ..core.sqlite import sqlite_transaction_async
from .embedding.embedding_service import MemoryEmbeddingService
from .l0.working_memory import L0WorkingMemoryStore
from .l1.event_store import L1EventStore
from .l2.store import L2CognitionStore
from .l2.entities.catalog import L2EntityCatalog
from .l2.llm_service import L2LLMService
from .l2.pipeline import L2Pipeline
from .l3.contradiction_service import ContradictionInsightService
from .l3.state_change_service import StateChangeService
from .l3.summary_store import L3SummaryStore
from .l3.task_reflection_service import TaskReflectionService
from .l3.trend_shift_service import TrendShiftService
from .l4.procedural_memory import L4ProceduralMemoryStore
from .hybrid_retrieval.entity_semantic_builder import EntityScopedSemanticBuilder
from .store_ingestion import MEMORY_INGEST_DIAGNOSTIC_EVENT_TYPES, MemoryIngestionMixin
from .store_l3_insights import L3InsightsMixin
from .store_monitoring import MonitoringMixin

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..llm import ScenarioLLMPool


class UnifiedMemoryStore(MemoryIngestionMixin, L3InsightsMixin, MonitoringMixin):
    """Coordinates the lifecycle-based L0-L4 memory stores."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        persist_dir: Optional[str] = None,
        *,
        l1_db_path: Optional[str] = None,
        memory_db_path: Optional[str] = None,
        enable_l0: bool = True,
        enable_l1: bool = True,
        enable_l2: bool = True,
        enable_l3: bool = True,
        enable_l4: bool = True,
        l0_checkpoint_interval_seconds: int = 30,
        l2_batch_flush_interval_seconds: int = 60,
        enable_l2_conflict_arbitration: bool = True,
        l2_conflict_arbitration_min_confidence: float = 0.85,
        session_timeout_seconds: int = 3600,
        embedding_service: MemoryEmbeddingService | None = None,
        scenario_llm_pool: "ScenarioLLMPool | None" = None,
        memory_config_getter: Callable[[], Any] | None = None,
        async_embeddings: bool = True,
        enable_l1_vectors: bool = True,
        enable_l2_vectors: bool = True,
        enable_l3_vectors: bool = True,
        enable_l4_vectors: bool = True,
        enable_l3_llm_summary: bool = True,
        temporal_l3_llm_timeout_seconds: float = 3.0,
        temporal_l3_llm_min_event_count: int = 2,
        temporal_summary_features_builder: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        from ..utils.runtime import get_runtime_paths

        runtime_paths = get_runtime_paths()
        memory_dir = Path(persist_dir).expanduser() if persist_dir else runtime_paths.memory_dir
        memory_dir.mkdir(parents=True, exist_ok=True)
        l1_db = str(
            (
                Path(l1_db_path).expanduser()
                if l1_db_path
                else (Path(db_path).expanduser() if db_path else runtime_paths.l1_memory_db_path)
            )
        )
        shared_memory_db = str(
            Path(memory_db_path).expanduser()
            if memory_db_path
            else (memory_dir / "memory.db")
        )
        archive_dir = memory_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        self.l0: Optional[L0WorkingMemoryStore] = None
        self.l1: Optional[L1EventStore] = None
        self.l2: Optional[L2CognitionStore] = None
        self.l2_entity_catalog: Optional[L2EntityCatalog] = None
        self.l2_llm_service: Optional[L2LLMService] = None
        self.l2_pipeline: Optional[L2Pipeline] = None
        self.l3: Optional[L3SummaryStore] = None
        self.l4: Optional[L4ProceduralMemoryStore] = None
        self._contradiction_service = ContradictionInsightService()
        self._task_reflection_service = TaskReflectionService()
        self._state_change_service = StateChangeService()
        self._trend_shift_service = TrendShiftService()
        self._archive_dir = archive_dir
        # Cap concurrent L3 summary generations so a herd of activity-summary
        # schedules cannot saturate the local LLM pool at integer hour boundaries.
        self._summary_semaphore: asyncio.Semaphore = asyncio.Semaphore(3)

        if enable_l0:
            self.l0 = L0WorkingMemoryStore(
                checkpoint_db_path=shared_memory_db,
                checkpoint_interval_seconds=l0_checkpoint_interval_seconds,
                session_timeout_seconds=session_timeout_seconds,
                restore_on_restart=True,
            )
        if enable_l1:
            self.l1 = L1EventStore(
                db_path=l1_db,
                embedding_service=embedding_service,
                memory_config_getter=memory_config_getter,
                vector_enabled=enable_l1_vectors,
                async_embeddings=async_embeddings,
            )
        if enable_l2:
            self.l2 = L2CognitionStore(db_path=shared_memory_db)
            self.l2_entity_catalog = L2EntityCatalog(
                db_path=shared_memory_db,
                embedding_service=embedding_service,
                memory_config_getter=memory_config_getter,
                vector_enabled=enable_l2_vectors,
            )
            self.l2_llm_service = L2LLMService(scenario_llm_pool)
            semantic_edge_builder: EntityScopedSemanticBuilder | None = None
            if self.l1 is not None:
                semantic_edge_builder = EntityScopedSemanticBuilder(
                    l1_store=self.l1,
                    l2_store=self.l2,
                    config_getter=memory_config_getter,
                )
            self.l2_pipeline = L2Pipeline(
                self.l2,
                l1_store=self.l1,
                entity_catalog=self.l2_entity_catalog,
                llm_service=self.l2_llm_service,
                state_change_callback=self._handle_l2_state_change_outcomes,
                active_entity_callback=self._handle_l2_active_entities,
                batch_flush_interval_seconds=l2_batch_flush_interval_seconds,
                enable_conflict_arbitration=enable_l2_conflict_arbitration,
                conflict_arbitration_min_confidence=l2_conflict_arbitration_min_confidence,
                semantic_edge_builder=semantic_edge_builder,
            )
        if enable_l3:
            self.l3 = L3SummaryStore(
                db_path=shared_memory_db,
                embedding_service=embedding_service,
                memory_config_getter=memory_config_getter,
                vector_enabled=enable_l3_vectors,
                async_embeddings=async_embeddings,
                enable_temporal_llm_summary=enable_l3_llm_summary,
                temporal_llm_timeout_seconds=temporal_l3_llm_timeout_seconds,
                temporal_llm_min_event_count=temporal_l3_llm_min_event_count,
                scenario_llm_pool=scenario_llm_pool,
                temporal_summary_features_builder=temporal_summary_features_builder,
            )
        if enable_l4:
            self.l4 = L4ProceduralMemoryStore(
                db_path=shared_memory_db,
                embedding_service=embedding_service,
                memory_config_getter=memory_config_getter,
                scenario_llm_pool=scenario_llm_pool,
                vector_enabled=enable_l4_vectors,
                async_embeddings=async_embeddings,
            )

        self._initialized = False
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize enabled stores."""
        if self._initialized:
            return

        for store in (self.l0, self.l1, self.l2, self.l2_entity_catalog, self.l3, self.l4):
            if store is None:
                continue
            await store.initialize()
        if self.l2_pipeline is not None:
            await self.l2_pipeline.start()

        self._initialized = True
        logger.info("Unified memory store initialized")

    async def replay_l2_extraction(self, event_id: str) -> bool:
        """Replay L2 extraction for an already stored L1 event."""
        if self.l1 is None or self.l2_pipeline is None:
            return False
        event = await self.l1.get_memory_event(event_id)
        if event is None:
            return False
        return await self.l2_pipeline.enqueue_event(event)

    async def reconcile_entities(self, entity_ids: list[str]) -> bool:
        """Trigger entity-level reconcile for one or more entities."""
        if self.l2_pipeline is None:
            return False
        return await self.l2_pipeline.enqueue_entities(entity_ids)

    async def refresh_l2_snapshots(self, entity_ids: list[str]) -> bool:
        """Trigger snapshot materialization for one or more entities."""
        if self.l2_pipeline is None:
            return False
        return await self.l2_pipeline.enqueue_snapshot_refresh(entity_ids)

    async def flush_l2_microbatches(self) -> int:
        """Flush all currently staged L2 microbatches into extract jobs."""
        if self.l2_pipeline is None:
            return 0
        return await self.l2_pipeline.flush_all_pending_batches()

    async def generate_summary(
        self,
        period_type: str = "day",
        *,
        period_start: Optional[float] = None,
        period_end: Optional[float] = None,
        summary_category: Optional[str] = None,
        source_filter: Optional[list[str]] = None,
        min_events: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """Generate a temporal L3 summary for a time window."""
        if self.l1 is None or self.l3 is None:
            return None

        now = time.time()
        if period_end is None:
            period_end = now
        if period_start is None:
            period_start = period_end - self._period_seconds(period_type)
        async with self._summary_semaphore:
            return await self.l3.generate_temporal_summary(
                l1_store=self.l1,
                summary_category=summary_category or period_type,
                period_start=period_start,
                period_end=period_end,
                source_filter=source_filter,
                min_events=min_events,
            )

    async def generate_source_activity_summary(
        self,
        *,
        summary_category: str,
        source_filter: list[str],
        period_type: str = "day",
        period_start: Optional[float] = None,
        period_end: Optional[float] = None,
        min_events: int = 4,
    ) -> Optional[Dict[str, Any]]:
        """Generate an L3 activity summary scoped to one or more sensor sources."""
        return await self.generate_summary(
            period_type=period_type,
            period_start=period_start,
            period_end=period_end,
            summary_category=summary_category,
            source_filter=source_filter,
            min_events=min_events,
        )

    async def generate_thematic_summary(
        self,
        *,
        topic: str,
        period_start: Optional[float] = None,
        period_end: Optional[float] = None,
        min_source_count: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """Generate a topic-oriented thematic L3 summary."""
        if self.l1 is None or self.l3 is None:
            return None
        return await self.l3.generate_thematic_summary(
            l1_store=self.l1,
            topic=topic,
            period_start=period_start,
            period_end=period_end,
            min_source_count=min_source_count,
        )

    async def search(self, query: str, *, search_type: str = "detail", limit: int = 10) -> list[dict[str, Any]]:
        """Perform a simple layer-aware search without the retrieval router."""
        if search_type in {"detail", "hybrid", "keyword"} and self.l1 is not None:
            return await self.l1.search_events(query=query, limit=limit)
        if search_type == "summary" and self.l3 is not None:
            return await self.l3.search_summaries(query=query, limit=limit)
        if search_type in {"experience", "strategy"} and self.l4 is not None:
            return await self.l4.query_strategies(query=query, limit=limit)
        if search_type == "graph" and self.l2 is not None:
            return await self.l2.get_relationships(limit=limit)
        return []

    def _archive_db_path_for_date(self, archive_date: str) -> Path:
        return self._archive_dir / f"{archive_date}.db"

    async def _archive_l1_event(self, event: Dict[str, Any], *, archived_at: float) -> None:
        archive_date = datetime.fromtimestamp(archived_at, tz=timezone.utc).strftime("%Y-%m-%d")
        archive_db_path = self._archive_db_path_for_date(archive_date)
        payload_json = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        async with sqlite_transaction_async(archive_db_path, profile="mixed") as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS archived_l1_events (
                    event_id TEXT PRIMARY KEY,
                    archived_date TEXT NOT NULL,
                    archived_at REAL NOT NULL,
                    event_timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    session_id TEXT,
                    user_id TEXT,
                    payload_json TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_archived_l1_events_date ON archived_l1_events(archived_date, event_timestamp)"
            )
            await db.execute(
                """
                INSERT OR REPLACE INTO archived_l1_events (
                    event_id, archived_date, archived_at, event_timestamp,
                    event_type, source, session_id, user_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    archive_date,
                    float(archived_at),
                    float(event.get("timestamp") or archived_at),
                    str(event.get("event_type") or "unknown"),
                    str(event.get("source") or "unknown"),
                    event.get("session_id"),
                    event.get("user_id"),
                    payload_json,
                ),
            )

    async def cleanup_old_data(
        self,
        older_than_days: int = 30,
        *,
        history_behavior: str = "delete",
    ) -> Dict[str, int]:
        """Run lightweight cleanup jobs."""
        removed: Dict[str, int] = {
            "expired_sessions": 0,
            "deleted_events": 0,
            "archived_events": 0,
            "deleted_summaries": 0,
        }
        if self.l0 is not None:
            removed["expired_sessions"] = len(await self.l0.expire_idle_sessions())
            await self.l0.checkpoint_all()
        if self.l1 is not None and self.l3 is not None:
            cutoff = time.time() - (max(int(older_than_days), 0) * 86400)
            candidate_event_ids = await self.l1.list_compressible_event_ids(
                older_than=cutoff,
                limit=10_000,
            )
            linked_event_ids = await self.l3.filter_linked_event_ids(candidate_event_ids)
            should_archive = str(history_behavior).lower() == "archive"
            archived_at = time.time()
            for event_id in linked_event_ids:
                if should_archive:
                    event = await self.l1.get_event(event_id)
                    if event is None:
                        continue
                    await self._archive_l1_event(event, archived_at=archived_at)
                    removed["archived_events"] += 1
                if await self.l1.mark_deleted(event_id):
                    removed["deleted_events"] += 1
        return removed

    async def run_maintenance(
        self,
        retention_days: int = 30,
        *,
        history_behavior: str = "delete",
    ) -> Dict[str, int]:
        """Run periodic maintenance."""
        return await self.cleanup_old_data(
            older_than_days=retention_days,
            history_behavior=history_behavior,
        )

    async def shutdown(self) -> None:
        """Drain asynchronous workers and close store resources."""
        if self.l2_pipeline is not None:
            await self.l2_pipeline.shutdown()
        for store in (self.l1, self.l3, self.l4):
            if store is None or not hasattr(store, "shutdown"):
                continue
            await store.shutdown()

    async def on_session_end(self, session_id: str) -> list[str]:
        """Notify that a chat session run has completed.

        Flushes any remaining L2 staged events for *session_id* and enqueues a
        comprehensive reconciliation of all entities touched during the session.
        Returns the entity_ids scheduled for session-end reconciliation.
        """
        if not session_id or self.l2_pipeline is None:
            return []
        return await self.l2_pipeline.flush_session(session_id)
    async def upsert_user_graph_edge(
        self,
        *,
        subject_id: str,
        subject_type: str,
        predicate: str,
        object_id: str,
        object_type: str,
        fact_kind: str | None = None,
        evidence_event_ids: list[str],
        confidence: float,
        observed_at: float,
        source_type: str,
        subject_attributes: Optional[Dict[str, Any]] = None,
        object_attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write a knowledge-graph edge through the unified cognition store."""
        _ = subject_attributes
        _ = object_attributes
        if self.l2 is None:
            return
        await self.l2.upsert_knowledge_edge(
            subject_id=subject_id,
            subject_type=subject_type,
            predicate=predicate,
            object_id=object_id,
            object_type=object_type,
            fact_kind=fact_kind,
            evidence_event_ids=evidence_event_ids,
            confidence=confidence,
            observed_at=observed_at,
            source_type=source_type,
        )

    def _period_seconds(self, period_type: str) -> int:
        return {
            "hour": 60 * 60,
            "day": 24 * 60 * 60,
            "week": 7 * 24 * 60 * 60,
            "month": 30 * 24 * 60 * 60,
        }.get(period_type, 24 * 60 * 60)


__all__ = [
    "UnifiedMemoryStore",
]
