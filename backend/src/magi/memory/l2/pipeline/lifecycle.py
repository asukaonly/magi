"""Lifecycle, defaults, and runtime state setup for L2Pipeline."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol

from ....core.logger import get_logger
from ...event_contracts import MemoryEvent
from ...hybrid_retrieval.entity_semantic_builder import EntityScopedSemanticBuilder
from ...l1.event_store import L1EventStore
from ..entities.catalog import L2EntityCatalog
from ..llm_service import L2LLMService
from ..models import (
    L2BatchJob,
    L2FocalEntityRef,
    L2PendingBatchBucket,
    ReconciledTraitOutcome,
)
from ..promotion_counter import L2PromotionCounter
from ..store import L2CognitionStore
from .staging import DEFAULT_L2_MAX_EVENTS_PER_BATCH

logger = get_logger(__name__)

DEFAULT_L2_EXTRACT_WORKER_COUNT = 5
DEFAULT_L2_BATCH_FLUSH_INTERVAL_SECONDS = 60
DEFAULT_L2_BATCH_SHUTDOWN_TIMEOUT_SECONDS = 2.0
DEFAULT_L2_PROJECTION_CLAIM_LIMIT = (
    DEFAULT_L2_MAX_EVENTS_PER_BATCH * DEFAULT_L2_EXTRACT_WORKER_COUNT
)
DEFAULT_L2_PROJECTION_STALE_QUEUED_TIMEOUT_SECONDS = 1800.0
DEFAULT_L2_PROJECTION_STALE_RUNNING_TIMEOUT_SECONDS = 300.0
DEFAULT_L2_PROJECTION_HEARTBEAT_INTERVAL_SECONDS = 30.0
DEFAULT_ENABLE_L2_CONFLICT_ARBITRATION = True
DEFAULT_L2_CONFLICT_ARBITRATION_MIN_CONFIDENCE = 0.85


@dataclass(slots=True)
class L2PipelineStats:
    """Counters for the staged L2 background pipeline."""

    is_running: bool = False
    extract_enqueued: int = 0
    extract_active: int = 0
    extract_completed: int = 0
    extract_failed: int = 0
    extract_skipped: int = 0
    reconcile_enqueued: int = 0
    reconcile_active: int = 0
    reconcile_completed: int = 0
    reconcile_failed: int = 0
    snapshot_enqueued: int = 0
    snapshot_active: int = 0
    snapshot_completed: int = 0
    snapshot_failed: int = 0
    relations_written: int = 0
    assertions_written: int = 0
    batch_flush_count: int = 0
    batch_flush_by_reason: dict[str, int] = field(default_factory=dict)
    pending_staged_event_count: int = 0
    active_bucket_count: int = 0
    avg_batch_event_count: float = 0.0
    avg_batch_estimated_tokens: float = 0.0
    extract_by_evidence_class: dict[str, int] = field(default_factory=dict)
    skip_by_reason: dict[str, int] = field(default_factory=dict)
    conflict_arbitration_triggered: int = 0
    conflict_arbitration_by_decision: dict[str, int] = field(default_factory=dict)
    severe_contradiction_hint_count: int = 0


class _L2PipelineLifecycleHostProtocol(Protocol):
    _cognition_store: L2CognitionStore | None
    _l1_store: L1EventStore | None
    _entity_catalog: L2EntityCatalog | None
    _promotion_counter: L2PromotionCounter | None
    _llm_service: L2LLMService | None
    _semantic_edge_builder: EntityScopedSemanticBuilder | None
    _state_change_callback: (
        Callable[[str, str, list[ReconciledTraitOutcome]], Awaitable[None]] | None
    )
    _active_entity_callback: Callable[[MemoryEvent, list[L2FocalEntityRef]], Awaitable[None]] | None
    _extraction_profile_provider: Callable[[], Iterable[Any]] | None
    _batch_flush_interval_seconds: int
    _enable_conflict_arbitration: bool
    _conflict_arbitration_min_confidence: float
    _extract_queue: asyncio.Queue[L2BatchJob | None]
    _reconcile_queue: asyncio.Queue[list[str] | None]
    _snapshot_queue: asyncio.Queue[list[str] | None]
    _extract_worker_count: int
    _extract_workers: list[asyncio.Task[None]]
    _flush_worker: asyncio.Task[None] | None
    _reconcile_worker: asyncio.Task[None] | None
    _snapshot_worker: asyncio.Task[None] | None
    _staging_buckets: dict[str, L2PendingBatchBucket]
    _staging_lock: asyncio.Lock
    _entity_locks: dict[str, asyncio.Lock]
    _entity_locks_guard: asyncio.Lock
    _session_touched_entities: dict[str, set[str]]
    _entity_resolution_cache: dict[tuple[str, str | None], tuple[str | None, float | None]]
    _stats: L2PipelineStats
    _projection_consumer_name: str
    _projection_claim_limit: int
    _projection_heartbeat_interval_seconds: float
    _projection_stale_queued_timeout_seconds: float
    _projection_stale_running_timeout_seconds: float
    _lifecycle_epoch: int
    _operation_guard_factory: Callable[[], Any] | None

    async def _run_extract_worker(self) -> None: ...

    async def _run_flush_worker(self) -> None: ...

    async def _run_reconcile_worker(self) -> None: ...

    async def _run_snapshot_worker(self) -> None: ...

    async def _flush_all_buckets(self, *, flush_reason: str) -> None: ...


class L2PipelineLifecycleMixin:
    """Own L2 pipeline runtime state initialization and lifecycle hooks."""

    def __init__(
        self,
        cognition_store: Optional[L2CognitionStore],
        *,
        l1_store: Optional[L1EventStore] = None,
        entity_catalog: Optional[L2EntityCatalog] = None,
        llm_service: Optional[L2LLMService] = None,
        state_change_callback: (
            Callable[[str, str, list[ReconciledTraitOutcome]], Awaitable[None]] | None
        ) = None,
        active_entity_callback: (
            Callable[[MemoryEvent, list[L2FocalEntityRef]], Awaitable[None]] | None
        ) = None,
        extraction_profile_provider: Callable[[], Iterable[Any]] | None = None,
        batch_flush_interval_seconds: int = DEFAULT_L2_BATCH_FLUSH_INTERVAL_SECONDS,
        enable_conflict_arbitration: bool = DEFAULT_ENABLE_L2_CONFLICT_ARBITRATION,
        conflict_arbitration_min_confidence: float = DEFAULT_L2_CONFLICT_ARBITRATION_MIN_CONFIDENCE,
        semantic_edge_builder: Optional[EntityScopedSemanticBuilder] = None,
        promotion_counter: Optional[L2PromotionCounter] = None,
    ) -> None:
        if cognition_store is not None and entity_catalog is None:
            raise ValueError("entity_catalog is required when cognition_store is enabled")
        if cognition_store is not None and llm_service is None:
            raise ValueError("llm_service is required when cognition_store is enabled")
        host = self._lifecycle_host()
        host._cognition_store = cognition_store
        host._l1_store = l1_store
        host._entity_catalog = entity_catalog
        host._llm_service = llm_service
        host._semantic_edge_builder = semantic_edge_builder
        host._promotion_counter = promotion_counter
        host._state_change_callback = state_change_callback
        host._active_entity_callback = active_entity_callback
        host._extraction_profile_provider = extraction_profile_provider
        host._batch_flush_interval_seconds = max(0, int(batch_flush_interval_seconds))
        host._enable_conflict_arbitration = bool(enable_conflict_arbitration)
        host._conflict_arbitration_min_confidence = max(
            0.0, min(1.0, float(conflict_arbitration_min_confidence))
        )
        host._extract_queue = asyncio.Queue()
        host._reconcile_queue = asyncio.Queue()
        host._snapshot_queue = asyncio.Queue()
        host._extract_worker_count = DEFAULT_L2_EXTRACT_WORKER_COUNT
        host._extract_workers = []
        host._flush_worker = None
        host._reconcile_worker = None
        host._snapshot_worker = None
        host._staging_buckets = {}
        host._staging_lock = asyncio.Lock()
        host._entity_locks = {}
        host._entity_locks_guard = asyncio.Lock()
        host._session_touched_entities = {}
        host._entity_resolution_cache = {}
        host._stats = L2PipelineStats()
        host._projection_consumer_name = f"l2-pipeline:{uuid.uuid4().hex[:8]}"
        host._projection_claim_limit = DEFAULT_L2_PROJECTION_CLAIM_LIMIT
        host._projection_heartbeat_interval_seconds = (
            DEFAULT_L2_PROJECTION_HEARTBEAT_INTERVAL_SECONDS
        )
        host._projection_stale_queued_timeout_seconds = (
            DEFAULT_L2_PROJECTION_STALE_QUEUED_TIMEOUT_SECONDS
        )
        host._projection_stale_running_timeout_seconds = (
            DEFAULT_L2_PROJECTION_STALE_RUNNING_TIMEOUT_SECONDS
        )
        host._lifecycle_epoch = 0
        host._operation_guard_factory = None

    def set_operation_guard_factory(self, factory: Callable[[], Any]) -> None:
        """Bind the unified clear barrier used by every pipeline job."""
        self._lifecycle_host()._operation_guard_factory = factory

    @asynccontextmanager
    async def _memory_operation_guard(self) -> AsyncIterator[None]:
        factory = self._lifecycle_host()._operation_guard_factory
        if factory is None:
            yield
            return
        async with factory():
            yield

    async def start(self) -> None:
        host = self._lifecycle_host()
        if host._stats.is_running or host._cognition_store is None:
            return

        host._lifecycle_epoch += 1
        start_epoch = host._lifecycle_epoch
        host._stats.is_running = True
        try:
            recovered_count = await host._cognition_store.recover_foreign_projection_jobs(
                consumer_name=host._projection_consumer_name
            )
        except BaseException:
            if host._lifecycle_epoch == start_epoch:
                host._stats.is_running = False
            raise
        if host._lifecycle_epoch != start_epoch or not host._stats.is_running:
            return
        if recovered_count:
            logger.info(
                "L2 projection attempts recovered on startup",
                consumer_name=host._projection_consumer_name,
                recovered_count=recovered_count,
            )
        host._extract_workers = [
            asyncio.create_task(host._run_extract_worker())
            for _ in range(host._extract_worker_count)
        ]
        host._flush_worker = asyncio.create_task(host._run_flush_worker())
        host._reconcile_worker = asyncio.create_task(host._run_reconcile_worker())
        host._snapshot_worker = asyncio.create_task(host._run_snapshot_worker())

    async def shutdown(self) -> None:
        host = self._lifecycle_host()
        if not host._stats.is_running:
            return

        host._lifecycle_epoch += 1
        host._stats.is_running = False
        if host._flush_worker is not None:
            host._flush_worker.cancel()
            try:
                await host._flush_worker
            except asyncio.CancelledError:
                pass
        try:
            await asyncio.wait_for(
                host._flush_all_buckets(flush_reason="shutdown"),
                timeout=DEFAULT_L2_BATCH_SHUTDOWN_TIMEOUT_SECONDS,
            )
        except (asyncio.TimeoutError, Exception):
            logger.warning("L2 shutdown flush timed out")
        for _ in host._extract_workers:
            await host._extract_queue.put(None)
        if host._reconcile_worker is not None:
            await host._reconcile_queue.put(None)
        if host._snapshot_worker is not None:
            await host._snapshot_queue.put(None)

        for worker in [*host._extract_workers, host._reconcile_worker, host._snapshot_worker]:
            if worker is None:
                continue
            try:
                await worker
            except asyncio.CancelledError:
                pass

        host._extract_workers = []
        host._flush_worker = None
        host._reconcile_worker = None
        host._snapshot_worker = None

    async def abort_for_clear(self) -> None:
        """Cancel workers and discard pending work without flushing it."""
        host = self._lifecycle_host()
        host._lifecycle_epoch += 1
        host._stats.is_running = False
        workers = [
            *host._extract_workers,
            host._flush_worker,
            host._reconcile_worker,
            host._snapshot_worker,
        ]
        for worker in workers:
            if worker is not None and not worker.done():
                worker.cancel()
        await asyncio.gather(
            *(worker for worker in workers if worker is not None),
            return_exceptions=True,
        )
        host._extract_workers = []
        host._flush_worker = None
        host._reconcile_worker = None
        host._snapshot_worker = None

    async def reset_after_clear(self) -> None:
        """Discard all process-local pipeline state after a destructive clear."""
        host = self._lifecycle_host()
        if host._stats.is_running:
            raise RuntimeError("L2 pipeline must be stopped before reset")
        host._lifecycle_epoch += 1
        async with host._staging_lock:
            host._staging_buckets = {}
        host._extract_queue = asyncio.Queue()
        host._reconcile_queue = asyncio.Queue()
        host._snapshot_queue = asyncio.Queue()
        host._entity_locks = {}
        host._entity_locks_guard = asyncio.Lock()
        host._session_touched_entities = {}
        host._entity_resolution_cache = {}
        host._stats = L2PipelineStats()
        host._projection_consumer_name = f"l2-pipeline:{uuid.uuid4().hex[:8]}"

    async def _acquire_entity_locks(self, entity_ids: list[str]) -> list[asyncio.Lock]:
        """Acquire per-entity locks in sorted order to prevent deadlocks.

        Returns the list of acquired locks (caller must release them).
        """
        host = self._lifecycle_host()
        locks: list[asyncio.Lock] = []
        for eid in sorted(entity_ids):
            async with host._entity_locks_guard:
                lock = host._entity_locks.get(eid)
                if lock is None:
                    lock = asyncio.Lock()
                    host._entity_locks[eid] = lock
            await lock.acquire()
            locks.append(lock)
        return locks

    def _lifecycle_host(self) -> _L2PipelineLifecycleHostProtocol:
        return self  # type: ignore[return-value]


__all__ = [
    "DEFAULT_ENABLE_L2_CONFLICT_ARBITRATION",
    "DEFAULT_L2_BATCH_FLUSH_INTERVAL_SECONDS",
    "DEFAULT_L2_BATCH_SHUTDOWN_TIMEOUT_SECONDS",
    "DEFAULT_L2_EXTRACT_WORKER_COUNT",
    "DEFAULT_L2_PROJECTION_CLAIM_LIMIT",
    "DEFAULT_L2_PROJECTION_STALE_QUEUED_TIMEOUT_SECONDS",
    "DEFAULT_L2_PROJECTION_STALE_RUNNING_TIMEOUT_SECONDS",
    "DEFAULT_L2_CONFLICT_ARBITRATION_MIN_CONFIDENCE",
    "L2PipelineLifecycleMixin",
    "L2PipelineStats",
]
