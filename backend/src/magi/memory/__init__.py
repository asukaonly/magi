"""Unified entrypoints for the rewritten L0-L4 memory system."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any, Dict, Optional

from ..events.events import Event, EventLevel
from .embedding_service import MemoryEmbeddingService
from .event_contracts import IngestTarget, MemoryEvent, normalize_runtime_event
from .identity_resolver import IdentityResolver
from .identity_migration import migrate_legacy_self_identity
from .l0.working_memory import L0WorkingMemoryStore
from .l1.event_store import L1EventStore
from .l2.store import L2CognitionStore
from .l2.entity_catalog import L2EntityCatalog
from .l2.llm_service import L2LLMService
from .l2.models import ManualL2EventRequest
from .l2.pipeline import L2Pipeline
from .l3.models import L3Candidate, TaskOutcomePacket
from .l3.summary_store import L3SummaryStore
from .l3.task_reflection_service import TaskReflectionService
from .l3.validator import validate_candidate
from .l4.procedural_memory import L4ProceduralMemoryStore

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..llm import ScenarioLLMPool


class UnifiedMemoryStore:
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
        session_timeout_seconds: int = 3600,
        embedding_service: MemoryEmbeddingService | None = None,
        scenario_llm_pool: "ScenarioLLMPool | None" = None,
        async_embeddings: bool = True,
        enable_l1_vectors: bool = True,
        enable_l3_vectors: bool = True,
        enable_l4_vectors: bool = True,
        enable_l3_llm_summary: bool = True,
        temporal_l3_llm_timeout_seconds: float = 3.0,
        temporal_l3_llm_min_event_count: int = 2,
        identity_resolver: IdentityResolver | None = None,
    ) -> None:
        from ..utils.runtime import get_runtime_paths

        runtime_paths = get_runtime_paths()
        memories_dir = Path(persist_dir).expanduser() if persist_dir else runtime_paths.memories_dir
        memories_dir.mkdir(parents=True, exist_ok=True)
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
            else (memories_dir / "memory.db")
        )

        self.l0: Optional[L0WorkingMemoryStore] = None
        self.l1: Optional[L1EventStore] = None
        self.l2: Optional[L2CognitionStore] = None
        self.l2_entity_catalog: Optional[L2EntityCatalog] = None
        self.l2_llm_service: Optional[L2LLMService] = None
        self.l2_pipeline: Optional[L2Pipeline] = None
        self.l3: Optional[L3SummaryStore] = None
        self.l4: Optional[L4ProceduralMemoryStore] = None
        self.identity_resolver = identity_resolver or IdentityResolver(db_path=shared_memory_db)
        self._task_reflection_service = TaskReflectionService()

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
                vector_enabled=enable_l1_vectors,
                async_embeddings=async_embeddings,
            )
        if enable_l2:
            self.l2 = L2CognitionStore(db_path=shared_memory_db)
            self.l2_entity_catalog = L2EntityCatalog(db_path=shared_memory_db)
            self.l2_llm_service = L2LLMService(scenario_llm_pool)
            self.l2_pipeline = L2Pipeline(
                self.l2,
                l1_store=self.l1,
                entity_catalog=self.l2_entity_catalog,
                llm_service=self.l2_llm_service,
            )
        if enable_l3:
            self.l3 = L3SummaryStore(
                db_path=shared_memory_db,
                embedding_service=embedding_service,
                vector_enabled=enable_l3_vectors,
                async_embeddings=async_embeddings,
                enable_temporal_llm_summary=enable_l3_llm_summary,
                temporal_llm_timeout_seconds=temporal_l3_llm_timeout_seconds,
                temporal_llm_min_event_count=temporal_l3_llm_min_event_count,
                scenario_llm_pool=scenario_llm_pool,
            )
        if enable_l4:
            self.l4 = L4ProceduralMemoryStore(
                db_path=shared_memory_db,
                embedding_service=embedding_service,
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
        await self.identity_resolver.initialize()
        await migrate_legacy_self_identity(
            l1_db_path=self.l1.db_path if self.l1 is not None else None,
            memory_db_path=self.l2.db_path if self.l2 is not None else None,
        )
        if self.l2_pipeline is not None:
            await self.l2_pipeline.start()

        self._initialized = True
        logger.info("Unified memory store initialized")

    async def ingest_event(self, event: Dict[str, Any] | Event | MemoryEvent) -> Dict[str, Any]:
        """Ingest an event through the new L0-L4 pipeline."""
        memory_event = self._normalize_event(event)
        l2_result = {"relation_count": 0, "assertion_count": 0}
        l4_skill_id: Optional[str] = None

        async with self._write_lock:
            if self.l0 is not None:
                await self.l0.capture_event(memory_event)

            if self.l1 is not None and memory_event.ingest_target.includes_l1:
                await self.l1.store(memory_event)
                if self.l2_pipeline is not None:
                    await self.l2_pipeline.enqueue_event(memory_event)
                if self.l4 is not None:
                    l4_skill_id = await self.l4.record_memory_event(memory_event)

        return {
            "event_id": memory_event.event_id,
            "ingest_target": memory_event.ingest_target.label,
            "l1_written": bool(self.l1 is not None and memory_event.ingest_target.includes_l1),
            "l2_relation_count": int(l2_result["relation_count"]),
            "l2_assertion_count": int(l2_result["assertion_count"]),
            "l4_skill_id": l4_skill_id,
        }

    async def store_event(self, event: Dict[str, Any] | Event | MemoryEvent) -> str:
        """Compatibility helper for callers that only need the event id."""
        result = await self.ingest_event(event)
        return str(result["event_id"])

    async def add_event(self, event: Dict[str, Any] | Event | MemoryEvent) -> str:
        """Store an event in the unified pipeline."""
        return await self.store_event(event)

    async def ingest_manual_l2_event(self, request: ManualL2EventRequest) -> Dict[str, Any]:
        """Inject a manual event into the normal L1 -> L2 path for testing."""
        payload = {
            "user_id": request.user_id,
            "session_id": request.session_id or f"manual-{request.user_id}",
            "message": request.text,
            "entity_focus_hint": request.entity_focus_hint,
        }
        metadata = {
            "manual_l2_lab": True,
            "entity_focus_hint": request.entity_focus_hint,
        }
        return await self.ingest_event(
            Event(
                type="USER_MESSAGE",
                data=payload,
                timestamp=time.time(),
                source=request.source,
                level=EventLevel.INFO,
                metadata=metadata,
                correlation_id=f"manual_{int(time.time() * 1000)}",
            )
        )

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

    async def generate_summary(
        self,
        period_type: str = "day",
        *,
        period_start: Optional[float] = None,
        period_end: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Generate a temporal L3 summary for a time window."""
        if self.l1 is None or self.l3 is None:
            return None

        now = time.time()
        if period_end is None:
            period_end = now
        if period_start is None:
            period_start = period_end - self._period_seconds(period_type)
        return await self.l3.generate_temporal_summary(
            l1_store=self.l1,
            summary_category=period_type,
            period_start=period_start,
            period_end=period_end,
        )

    async def persist_l3_candidate(
        self,
        *,
        candidate: L3Candidate,
        task_outcome: TaskOutcomePacket | None = None,
        source_task_ids: list[str] | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Validate and persist an explicit L3 candidate."""
        if self.l1 is None or self.l3 is None:
            return None

        evidence_events: list[dict[str, Any]] = []
        for event_id in candidate.source_event_ids:
            event = await self.l1.get_memory_event(event_id)
            if event is not None:
                evidence_events.append(event.to_dict() if hasattr(event, "to_dict") else dict(event))

        decision = validate_candidate(
            candidate,
            evidence_events=evidence_events,
            task_outcome=task_outcome,
        )
        if decision.action != "accept":
            return None

        task_ids = list(source_task_ids or [])
        if task_outcome is not None and task_outcome.task_id not in task_ids:
            task_ids.append(task_outcome.task_id)
        return await self.l3.upsert_candidate(candidate=candidate, source_task_ids=task_ids)

    async def persist_task_outcome_reflection(
        self,
        task_outcome: TaskOutcomePacket,
    ) -> Optional[Dict[str, Any]]:
        """Build and persist a task-driven L3 reflection when it has user value."""
        candidate = await self._task_reflection_service.build_candidate(task_outcome)
        if candidate is None:
            return None
        return await self.persist_l3_candidate(
            candidate=candidate,
            task_outcome=task_outcome,
            source_task_ids=[task_outcome.task_id],
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

    async def get_statistics(self) -> Dict[str, Any]:
        """Return per-layer statistics."""
        stats: Dict[str, Any] = {}
        if self.l0 is not None:
            stats["l0"] = {"checkpoint_db_path": self.l0.checkpoint_db_path}
        if self.l1 is not None:
            stats["l1"] = {
                "db_path": self.l1.db_path,
                "event_count": await self.l1.count_events(),
            }
        if self.l2 is not None:
            stats["l2"] = self.l2.get_statistics()
        if self.l2_pipeline is not None:
            stats["l2_pipeline"] = self.l2_pipeline.get_statistics()
        if self.l3 is not None:
            stats["l3"] = self.l3.get_statistics() if hasattr(self.l3, "get_statistics") else {"db_path": self.l3.db_path}
        if self.l4 is not None:
            stats["l4"] = self.l4.get_statistics()
        return stats

    async def cleanup_old_data(self, older_than_days: int = 30) -> Dict[str, int]:
        """Run lightweight cleanup jobs."""
        removed: Dict[str, int] = {"expired_sessions": 0, "deleted_events": 0, "deleted_summaries": 0}
        if self.l0 is not None:
            removed["expired_sessions"] = len(await self.l0.expire_idle_sessions())
            await self.l0.checkpoint_all()
        _ = older_than_days
        return removed

    async def run_maintenance(self, retention_days: int = 30) -> Dict[str, int]:
        """Run periodic maintenance."""
        return await self.cleanup_old_data(older_than_days=retention_days)

    async def shutdown(self) -> None:
        """Drain asynchronous workers and close store resources."""
        if self.l2_pipeline is not None:
            await self.l2_pipeline.shutdown()
        for store in (self.l1, self.l3, self.l4):
            if store is None or not hasattr(store, "shutdown"):
                continue
            await store.shutdown()
        await self.identity_resolver.shutdown()

    def get_l2_pipeline_stats(self) -> Dict[str, Any]:
        """Expose current background L2 pipeline counters."""
        if self.l2_pipeline is None:
            return {
                "is_running": False,
                "extract_enqueued": 0,
                "extract_completed": 0,
                "extract_failed": 0,
                "extract_skipped": 0,
                "reconcile_enqueued": 0,
                "reconcile_completed": 0,
                "reconcile_failed": 0,
                "snapshot_enqueued": 0,
                "snapshot_completed": 0,
                "snapshot_failed": 0,
                "relations_written": 0,
                "assertions_written": 0,
                "extract_by_evidence_class": {},
                "skip_by_reason": {},
            }
        return self.l2_pipeline.get_statistics()

    async def upsert_user_graph_edge(
        self,
        *,
        subject_id: str,
        subject_type: str,
        predicate: str,
        object_id: str,
        object_type: str,
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
            evidence_event_ids=evidence_event_ids,
            confidence=confidence,
            observed_at=observed_at,
            source_type=source_type,
        )

    def _normalize_event(self, event: Dict[str, Any] | Event | MemoryEvent) -> MemoryEvent:
        if isinstance(event, MemoryEvent):
            return event
        if isinstance(event, Event):
            return normalize_runtime_event(event, identity_resolver=self.identity_resolver)

        payload = dict(event)
        raw_event = Event(
            type=str(payload.get("type", "unknown")),
            data=payload.get("data", {}),
            timestamp=float(payload.get("timestamp", time.time())),
            source=str(payload.get("source", "memory")),
            level=EventLevel(int(payload.get("level", EventLevel.INFO.value))),
            correlation_id=payload.get("correlation_id"),
            metadata=dict(payload.get("metadata", {})),
        )
        return normalize_runtime_event(
            raw_event,
            event_id=payload.get("id") or payload.get("event_id"),
            identity_resolver=self.identity_resolver,
        )

    async def upsert_identity_link(
        self,
        *,
        namespace: str,
        runtime_user_id: str,
        memory_owner_id: str,
        link_type: str = "runtime_account",
    ) -> None:
        """Persist a runtime-to-memory identity link."""

        await self.identity_resolver.upsert_identity_link(
            namespace=namespace,
            runtime_user_id=runtime_user_id,
            memory_owner_id=memory_owner_id,
            link_type=link_type,
        )

    async def list_identity_links(self) -> list[dict[str, str]]:
        """Return runtime-to-memory identity links in a JSON-friendly shape."""

        links = await self.identity_resolver.list_identity_links()
        return [
            {
                "namespace": link.namespace,
                "runtime_user_id": link.runtime_user_id,
                "memory_owner_id": link.memory_owner_id,
                "link_type": link.link_type,
            }
            for link in links
        ]

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
