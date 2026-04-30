"""Unified L0-L4 memory store composition."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from .embedding.embedding_service import MemoryEmbeddingService
from .hybrid_retrieval.entity_semantic_builder import EntityScopedSemanticBuilder
from .l0.working_memory import L0WorkingMemoryStore
from .l1.event_store import L1EventStore
from .l2.entities.catalog import L2EntityCatalog
from .l2.llm_service import L2LLMService
from .l2.pipeline import L2Pipeline
from .l2.store import L2CognitionStore
from .l3.contradiction_service import ContradictionInsightService
from .l3.state_change_service import StateChangeService
from .l3.summary_store import L3SummaryStore
from .l3.task_reflection_service import TaskReflectionService
from .l3.trend_shift_service import TrendShiftService
from .l4.procedural_memory import L4ProceduralMemoryStore
from .store_ingestion import MemoryIngestionMixin
from .store_l2_operations import UnifiedMemoryL2OperationsMixin
from .store_l3_insights import L3InsightsMixin
from .store_lifecycle import UnifiedMemoryLifecycleMixin
from .store_maintenance import UnifiedMemoryMaintenanceMixin
from .store_monitoring import MonitoringMixin
from .store_summaries import UnifiedMemorySummaryMixin

if TYPE_CHECKING:
    from ..llm import ScenarioLLMPool


class UnifiedMemoryStore(
    MemoryIngestionMixin,
    L3InsightsMixin,
    MonitoringMixin,
    UnifiedMemoryLifecycleMixin,
    UnifiedMemoryL2OperationsMixin,
    UnifiedMemorySummaryMixin,
    UnifiedMemoryMaintenanceMixin,
):
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


__all__ = ["UnifiedMemoryStore"]
