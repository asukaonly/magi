"""Unified L0-L4 memory store composition."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from .embedding.embedding_service import MemoryEmbeddingService
from .hybrid_retrieval.entity_semantic_builder import EntityScopedSemanticBuilder
from .forgetting import DurableForgetRunner, SourceForgetOwnerRegistry
from .l0.working_memory import L0WorkingMemoryStore
from .l1.event_store import L1EventStore
from .l2.edge_embedding_drain import EdgeEmbeddingDrainer, L2EdgeEmbeddingWorker
from .l2.entities.catalog import L2EntityCatalog
from .l2.llm_service import L2LLMService
from .l2.pipeline import L2Pipeline
from .l2.promotion_counter import L2PromotionCounter
from .l2.store import L2CognitionStore
from .l3.contradiction_service import ContradictionInsightService
from .l3.state_change_service import StateChangeService
from .l3.summary_store import L3SummaryStore
from .l3.task_reflection_service import TaskReflectionService
from .l3.trend_shift_service import TrendShiftService
from .l4.procedural_memory import L4ProceduralMemoryStore
from .operation_barrier import AsyncOperationBarrier
from .store_ingestion import MemoryIngestionMixin
from .store_governed_l1_writes import UnifiedGovernedL1WriteMixin
from .store_corrections import UnifiedMemoryCorrectionMixin
from .store_l2_operations import UnifiedMemoryL2OperationsMixin
from .store_l3_insights import L3InsightsMixin
from .store_lifecycle import UnifiedMemoryLifecycleMixin
from .store_maintenance import UnifiedMemoryMaintenanceMixin
from .store_monitoring import MonitoringMixin
from .store_source_event_forgetting import UnifiedSourceEventForgettingMixin
from .store_summaries import UnifiedMemorySummaryMixin

if TYPE_CHECKING:
    from ..llm import ScenarioLLMPool


@dataclass(frozen=True)
class MemoryStoreTuning:
    """Advanced, rarely-overridden tuning knobs for ``UnifiedMemoryStore``.

    The common knobs — ``enable_l0..l4`` and ``l2_batch_flush_interval_seconds``
    — stay as explicit constructor parameters because callers (especially tests)
    toggle them often. These are the advanced knobs almost every caller leaves at
    their defaults; bundling them keeps the constructor signature focused on
    identity (paths), injected collaborators, and the common layer toggles.
    """

    enable_l1_vectors: bool = True
    enable_l2_vectors: bool = True
    enable_l3_vectors: bool = True
    enable_l4_vectors: bool = True
    enable_l3_llm_summary: bool = True
    async_embeddings: bool = True
    l0_checkpoint_interval_seconds: int = 30
    session_timeout_seconds: int = 3600
    temporal_l3_llm_timeout_seconds: float = 3.0
    temporal_l3_llm_min_event_count: int = 2


@dataclass(frozen=True)
class _MemoryStorePaths:
    memory_dir: Path
    l1_db_path: str
    shared_memory_db_path: str
    archive_dir: Path


@dataclass(frozen=True)
class _EnabledMemoryLayers:
    l0: bool
    l1: bool
    l2: bool
    l3: bool
    l4: bool


@dataclass(frozen=True)
class _MemoryStoreBuildContext:
    paths: _MemoryStorePaths
    tuning: MemoryStoreTuning
    embedding_service: MemoryEmbeddingService | None
    scenario_llm_pool: "ScenarioLLMPool | None"
    memory_config_getter: Callable[[], Any] | None
    temporal_summary_features_builder: Callable[..., dict[str, Any]] | None
    extraction_profile_provider: Callable[[], Any] | None


class UnifiedMemoryStore(
    MemoryIngestionMixin,
    UnifiedGovernedL1WriteMixin,
    UnifiedMemoryCorrectionMixin,
    L3InsightsMixin,
    MonitoringMixin,
    UnifiedMemoryLifecycleMixin,
    UnifiedMemoryL2OperationsMixin,
    UnifiedMemorySummaryMixin,
    UnifiedMemoryMaintenanceMixin,
    UnifiedSourceEventForgettingMixin,
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
        l2_batch_flush_interval_seconds: int = 60,
        embedding_service: MemoryEmbeddingService | None = None,
        scenario_llm_pool: "ScenarioLLMPool | None" = None,
        memory_config_getter: Callable[[], Any] | None = None,
        archive_dir_path: Optional[str] = None,
        temporal_summary_features_builder: Callable[..., dict[str, Any]] | None = None,
        extraction_profile_provider: Callable[[], Any] | None = None,
        tuning: "MemoryStoreTuning | None" = None,
    ) -> None:
        context = _MemoryStoreBuildContext(
            paths=self._resolve_memory_store_paths(
                db_path=db_path,
                persist_dir=persist_dir,
                l1_db_path=l1_db_path,
                memory_db_path=memory_db_path,
                archive_dir_path=archive_dir_path,
            ),
            tuning=tuning or MemoryStoreTuning(),
            embedding_service=embedding_service,
            scenario_llm_pool=scenario_llm_pool,
            memory_config_getter=memory_config_getter,
            temporal_summary_features_builder=temporal_summary_features_builder,
            extraction_profile_provider=extraction_profile_provider,
        )
        enabled_layers = _EnabledMemoryLayers(
            l0=enable_l0,
            l1=enable_l1,
            l2=enable_l2,
            l3=enable_l3,
            l4=enable_l4,
        )
        self.memory_db_path = context.paths.shared_memory_db_path
        self.l1_db_path = context.paths.l1_db_path
        self.scenario_llm_pool = scenario_llm_pool
        self._memory_config_getter = context.memory_config_getter
        self._portrait_projection_scheduler = None
        self._initialize_layer_slots(context.paths.archive_dir, l2_batch_flush_interval_seconds)
        self._build_enabled_layers(context, enabled_layers)
        self._finalize_initial_state()

    def _build_enabled_layers(
        self,
        context: _MemoryStoreBuildContext,
        enabled_layers: _EnabledMemoryLayers,
    ) -> None:
        if enabled_layers.l0:
            self.l0 = self._build_l0_store(context)
        if enabled_layers.l1:
            self.l1 = self._build_l1_store(context)
        if enabled_layers.l2:
            self._build_l2_stack(context)

        self._build_edge_embedding_worker(context)

        if enabled_layers.l3:
            self.l3 = self._build_l3_store(context, l1_store=self.l1)
        if enabled_layers.l4:
            self.l4 = self._build_l4_store(context)

    @staticmethod
    def _resolve_memory_store_paths(
        *,
        db_path: Optional[str],
        persist_dir: Optional[str],
        l1_db_path: Optional[str],
        memory_db_path: Optional[str],
        archive_dir_path: Optional[str],
    ) -> _MemoryStorePaths:
        from ..utils.runtime import get_runtime_paths

        runtime_paths = get_runtime_paths()
        memory_dir = Path(persist_dir).expanduser() if persist_dir else runtime_paths.memory_dir
        memory_dir.mkdir(parents=True, exist_ok=True)
        l1_db = str(
            Path(l1_db_path).expanduser()
            if l1_db_path
            else (Path(db_path).expanduser() if db_path else runtime_paths.l1_memory_db_path)
        )
        shared_memory_db = str(
            Path(memory_db_path).expanduser() if memory_db_path else (memory_dir / "memory.db")
        )
        archive_dir = (
            Path(archive_dir_path).expanduser() if archive_dir_path else memory_dir / "archive"
        )
        archive_dir.mkdir(parents=True, exist_ok=True)
        return _MemoryStorePaths(
            memory_dir=memory_dir,
            l1_db_path=l1_db,
            shared_memory_db_path=shared_memory_db,
            archive_dir=archive_dir,
        )

    def _finalize_initial_state(self) -> None:
        # NOTE: the manual-entry subsystem (store, asset store, weather fetcher)
        # and the location subsystem (sample store, geocode cache, resolver,
        # WiFi/IPGeo sources) are no longer built here. They are owned by
        # ``magi.memory.manual_entries.lifecycle.ManualEntriesModule`` and
        # ``magi.location.lifecycle.LocationModule`` respectively, and exposed
        # via their bootstrap-context slices + DI bindings. Memory's only stake
        # in manual entries is the L1 projection, built at the API boundary.

        self._initialized = False
        self._write_lock = asyncio.Lock()
        self._clear_barrier = AsyncOperationBarrier()
        self._clear_epoch = 0
        self._clear_request_count = 0
        self._post_turn_forget_operations: set[str] = set()
        self._source_forget_owners = SourceForgetOwnerRegistry(
            required_sources=("manual_entry",),
        )
        self._durable_forget_runner = DurableForgetRunner(self)
        if self.l2_pipeline is not None:
            self.l2_pipeline.set_operation_guard_factory(self.memory_operation_guard)
        for store in (self.l1, self.l3, self.l4):
            if store is not None:
                store.set_operation_guard_factory(self.memory_operation_guard)
        self._edge_embedding_worker.set_operation_guard_factory(self.memory_operation_guard)

    def _initialize_layer_slots(
        self,
        archive_dir: Path,
        l2_batch_flush_interval_seconds: int,
    ) -> None:
        self.l0: Optional[L0WorkingMemoryStore] = None
        self.l1: Optional[L1EventStore] = None
        self.l2: Optional[L2CognitionStore] = None
        self.l2_entity_catalog: Optional[L2EntityCatalog] = None
        self.l2_promotion_counter: Optional[L2PromotionCounter] = None
        self.l2_llm_service: Optional[L2LLMService] = None
        self.l2_pipeline: Optional[L2Pipeline] = None
        self._l2_batch_flush_interval_seconds = int(l2_batch_flush_interval_seconds)
        self.l3: Optional[L3SummaryStore] = None
        self.l4: Optional[L4ProceduralMemoryStore] = None
        self._contradiction_service = ContradictionInsightService()
        self._task_reflection_service = TaskReflectionService()
        self._state_change_service = StateChangeService()
        self._trend_shift_service = TrendShiftService()
        self._archive_dir = archive_dir
        self._summary_semaphore: asyncio.Semaphore = asyncio.Semaphore(3)

    @staticmethod
    def _build_l0_store(context: _MemoryStoreBuildContext) -> L0WorkingMemoryStore:
        return L0WorkingMemoryStore(
            checkpoint_db_path=context.paths.shared_memory_db_path,
            checkpoint_interval_seconds=context.tuning.l0_checkpoint_interval_seconds,
            session_timeout_seconds=context.tuning.session_timeout_seconds,
            restore_on_restart=True,
        )

    @staticmethod
    def _build_l1_store(context: _MemoryStoreBuildContext) -> L1EventStore:
        return L1EventStore(
            db_path=context.paths.l1_db_path,
            embedding_service=context.embedding_service,
            memory_config_getter=context.memory_config_getter,
            vector_enabled=context.tuning.enable_l1_vectors,
            async_embeddings=context.tuning.async_embeddings,
        )

    def _build_l2_stack(self, context: _MemoryStoreBuildContext) -> None:
        self.l2 = L2CognitionStore(
            db_path=context.paths.shared_memory_db_path,
            evidence_timestamp_resolver=(
                self.l1.get_event_timestamps if self.l1 is not None else None
            ),
        )
        if self.l1 is not None:
            self.l2.register_memory_correction_job_handler(
                "l1_audit",
                self.write_l1_correction_audit,
            )
        self.l2_entity_catalog = L2EntityCatalog(
            db_path=context.paths.shared_memory_db_path,
            embedding_service=context.embedding_service,
            memory_config_getter=context.memory_config_getter,
            vector_enabled=context.tuning.enable_l2_vectors,
        )
        self.l2_promotion_counter = L2PromotionCounter(db_path=context.paths.shared_memory_db_path)
        self.l2_llm_service = L2LLMService(context.scenario_llm_pool)
        semantic_edge_builder = self._build_semantic_edge_builder(context.memory_config_getter)
        self.l2_pipeline = L2Pipeline(
            self.l2,
            l1_store=self.l1,
            entity_catalog=self.l2_entity_catalog,
            llm_service=self.l2_llm_service,
            state_change_callback=self._handle_l2_state_change_outcomes,
            batch_flush_interval_seconds=self._l2_batch_flush_interval_seconds,
            semantic_edge_builder=semantic_edge_builder,
            extraction_profile_provider=context.extraction_profile_provider,
            promotion_counter=self.l2_promotion_counter,
        )

    def _build_semantic_edge_builder(
        self,
        memory_config_getter: Callable[[], Any] | None,
    ) -> EntityScopedSemanticBuilder | None:
        if self.l1 is None or self.l2 is None:
            return None
        return EntityScopedSemanticBuilder(
            l1_store=self.l1,
            l2_store=self.l2,
            config_getter=memory_config_getter,
        )

    def _build_edge_embedding_worker(self, context: _MemoryStoreBuildContext) -> None:
        # The worker is always constructed so stop() is safe during shutdown,
        # but initialize() starts it only when an embedding service is present.
        drain_interval = self._edge_embedding_drain_interval(context.memory_config_getter)
        self._edge_embedding_drainer = EdgeEmbeddingDrainer(
            db_path=context.paths.shared_memory_db_path,
            embedding_service=(
                self.l2_entity_catalog.embedding_service
                if self.l2_entity_catalog is not None
                else None
            ),
            edge_vector_index=(
                self.l2_entity_catalog.edge_vector_index
                if self.l2_entity_catalog is not None
                else None
            ),
        )
        self._edge_embedding_worker = L2EdgeEmbeddingWorker(
            drainer=self._edge_embedding_drainer,
            idle_interval_seconds=drain_interval,
        )

    @staticmethod
    def _edge_embedding_drain_interval(
        memory_config_getter: Callable[[], Any] | None,
    ) -> float:
        if memory_config_getter is None:
            return 5.0
        try:
            return memory_config_getter().l2.edge_embedding_drain_interval_seconds
        except Exception:
            return 5.0

    @staticmethod
    def _build_l3_store(
        context: _MemoryStoreBuildContext,
        *,
        l1_store: L1EventStore | None,
    ) -> L3SummaryStore:
        return L3SummaryStore(
            db_path=context.paths.shared_memory_db_path,
            embedding_service=context.embedding_service,
            memory_config_getter=context.memory_config_getter,
            vector_enabled=context.tuning.enable_l3_vectors,
            async_embeddings=context.tuning.async_embeddings,
            enable_temporal_llm_summary=context.tuning.enable_l3_llm_summary,
            temporal_llm_timeout_seconds=context.tuning.temporal_l3_llm_timeout_seconds,
            temporal_llm_min_event_count=context.tuning.temporal_l3_llm_min_event_count,
            scenario_llm_pool=context.scenario_llm_pool,
            temporal_summary_features_builder=context.temporal_summary_features_builder,
            evidence_timestamp_resolver=(
                l1_store.get_event_timestamps if l1_store is not None else None
            ),
        )

    @staticmethod
    def _build_l4_store(context: _MemoryStoreBuildContext) -> L4ProceduralMemoryStore:
        return L4ProceduralMemoryStore(
            db_path=context.paths.shared_memory_db_path,
            embedding_service=context.embedding_service,
            memory_config_getter=context.memory_config_getter,
            scenario_llm_pool=context.scenario_llm_pool,
            vector_enabled=context.tuning.enable_l4_vectors,
            async_embeddings=context.tuning.async_embeddings,
        )


__all__ = ["UnifiedMemoryStore", "MemoryStoreTuning"]
