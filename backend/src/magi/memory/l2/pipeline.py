"""Asynchronous queue workers for L2 cognition processing."""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ...core.logger import get_logger
from ..event_contracts import MemoryEvent
from ..l1.event_store import L1EventStore
from .context_bundle import ContextBundle, ResolvedContextRef
from .context_collector import collect_context_bundle
from .models import (
    ContradictionHint,
    L2BatchJob,
    L2ConflictArbitrationResult,
    L2EventWindow,
    L2EventWindowSummary,
    L2FocalEntityRef,
    L2HistoryContext,
    L2PendingBatchBucket,
    ReconciledTraitOutcome,
    ResolvedEntityMention,
    build_l2_batch_bucket_key,
)
from .store import L2CognitionStore
from .evidence_classifier import classify_event_evidence
from .evidence_policy import resolve_l2_policy
from .entity_catalog import L2EntityCatalog
from .extraction_profiles import ExtractionProfile, resolve_extraction_profile
from .llm_service import L2LLMService
from .episode_formation import assign_events_to_episode
from .models import EpisodeCandidateJob
from .ontology import coerce_unknown_entity_type
from .pipeline_conflict import L2ConflictArbitrationMixin
from .pipeline_entity import L2EntityResolutionMixin
from .pipeline_validation import L2ValidationMixin
from ..hybrid_retrieval.entity_semantic_builder import EntityScopedSemanticBuilder

_GENERIC_PREFERENCE_OBJECT_SUFFIXES = {
    "weather",
    "weather-state",
    "food",
    "music",
    "place",
}
logger = get_logger(__name__)
DEFAULT_L2_EXTRACT_WORKER_COUNT = 5
DEFAULT_L2_BATCH_FLUSH_INTERVAL_SECONDS = 60
DEFAULT_L2_FLUSH_POLL_INTERVAL_SECONDS = 0.2
DEFAULT_L2_MAX_EVENTS_PER_BATCH = 12
DEFAULT_L2_MAX_ESTIMATED_TOKENS_PER_BATCH = 2400
DEFAULT_L2_BATCH_SHUTDOWN_TIMEOUT_SECONDS = 2.0
DEFAULT_L2_PROJECTION_CLAIM_LIMIT = DEFAULT_L2_MAX_EVENTS_PER_BATCH * DEFAULT_L2_EXTRACT_WORKER_COUNT
DEFAULT_L2_PROJECTION_STALE_QUEUED_TIMEOUT_SECONDS = 1800.0
DEFAULT_L2_PROJECTION_STALE_RUNNING_TIMEOUT_SECONDS = 300.0
DEFAULT_L2_HISTORY_ENTITY_MATCH_LIMIT = 3
DEFAULT_L2_HISTORY_CONTEXT_LIMIT = 3
DEFAULT_L2_HISTORY_SEARCH_LIMIT = 4
DEFAULT_ENABLE_L2_CONFLICT_ARBITRATION = True
DEFAULT_L2_CONFLICT_ARBITRATION_MIN_CONFIDENCE = 0.85

@dataclass(slots=True)
class L2PipelineStats:
    """Counters for the staged L2 background pipeline."""

    is_running: bool = False
    extract_enqueued: int = 0
    extract_completed: int = 0
    extract_failed: int = 0
    extract_skipped: int = 0
    reconcile_enqueued: int = 0
    reconcile_completed: int = 0
    reconcile_failed: int = 0
    snapshot_enqueued: int = 0
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

class L2Pipeline(L2ConflictArbitrationMixin, L2EntityResolutionMixin, L2ValidationMixin):
    """Owns asynchronous L2 extraction and follow-up queues."""

    def __init__(
        self,
        cognition_store: Optional[L2CognitionStore],
        *,
        l1_store: Optional[L1EventStore] = None,
        entity_catalog: Optional[L2EntityCatalog] = None,
        llm_service: Optional[L2LLMService] = None,
        state_change_callback: Callable[[str, str, list[ReconciledTraitOutcome]], Awaitable[None]] | None = None,
        active_entity_callback: Callable[[MemoryEvent, list[L2FocalEntityRef]], Awaitable[None]] | None = None,
        batch_flush_interval_seconds: int = DEFAULT_L2_BATCH_FLUSH_INTERVAL_SECONDS,
        enable_conflict_arbitration: bool = DEFAULT_ENABLE_L2_CONFLICT_ARBITRATION,
        conflict_arbitration_min_confidence: float = DEFAULT_L2_CONFLICT_ARBITRATION_MIN_CONFIDENCE,
        semantic_edge_builder: Optional[EntityScopedSemanticBuilder] = None,
    ) -> None:
        if cognition_store is not None and entity_catalog is None:
            raise ValueError("entity_catalog is required when cognition_store is enabled")
        if cognition_store is not None and llm_service is None:
            raise ValueError("llm_service is required when cognition_store is enabled")
        self._cognition_store = cognition_store
        self._l1_store = l1_store
        self._entity_catalog = entity_catalog
        self._llm_service = llm_service
        self._semantic_edge_builder = semantic_edge_builder
        self._state_change_callback = state_change_callback
        self._active_entity_callback = active_entity_callback
        self._batch_flush_interval_seconds = max(0, int(batch_flush_interval_seconds))
        self._enable_conflict_arbitration = bool(enable_conflict_arbitration)
        self._conflict_arbitration_min_confidence = max(0.0, min(1.0, float(conflict_arbitration_min_confidence)))
        self._extract_queue: asyncio.Queue[L2BatchJob | None] = asyncio.Queue()
        self._reconcile_queue: asyncio.Queue[list[str] | None] = asyncio.Queue()
        self._snapshot_queue: asyncio.Queue[list[str] | None] = asyncio.Queue()
        self._extract_worker_count = DEFAULT_L2_EXTRACT_WORKER_COUNT
        self._extract_workers: list[asyncio.Task[None]] = []
        self._flush_worker: asyncio.Task[None] | None = None
        self._reconcile_worker: asyncio.Task[None] | None = None
        self._snapshot_worker: asyncio.Task[None] | None = None
        self._staging_buckets: dict[str, L2PendingBatchBucket] = {}
        self._staging_lock = asyncio.Lock()
        self._entity_locks: dict[str, asyncio.Lock] = {}
        self._entity_locks_guard = asyncio.Lock()
        self._session_touched_entities: dict[str, set[str]] = {}
        self._entity_resolution_cache: dict[tuple[str, str | None], tuple[str | None, float | None]] = {}
        self._stats = L2PipelineStats()
        self._projection_consumer_name = f"l2-pipeline:{uuid.uuid4().hex[:8]}"
        self._projection_claim_limit = DEFAULT_L2_PROJECTION_CLAIM_LIMIT
        self._projection_stale_queued_timeout_seconds = DEFAULT_L2_PROJECTION_STALE_QUEUED_TIMEOUT_SECONDS
        self._projection_stale_running_timeout_seconds = DEFAULT_L2_PROJECTION_STALE_RUNNING_TIMEOUT_SECONDS

    async def start(self) -> None:
        if self._stats.is_running or self._cognition_store is None:
            return

        self._stats.is_running = True
        self._extract_workers = [asyncio.create_task(self._run_extract_worker()) for _ in range(self._extract_worker_count)]
        self._flush_worker = asyncio.create_task(self._run_flush_worker())
        self._reconcile_worker = asyncio.create_task(self._run_reconcile_worker())
        self._snapshot_worker = asyncio.create_task(self._run_snapshot_worker())

    async def shutdown(self) -> None:
        if not self._stats.is_running:
            return

        self._stats.is_running = False
        if self._flush_worker is not None:
            self._flush_worker.cancel()
            try:
                await self._flush_worker
            except asyncio.CancelledError:
                pass
        try:
            await asyncio.wait_for(
                self._flush_all_buckets(flush_reason="shutdown"),
                timeout=DEFAULT_L2_BATCH_SHUTDOWN_TIMEOUT_SECONDS,
            )
        except (asyncio.TimeoutError, Exception):
            logger.warning("L2 shutdown flush timed out")
        for _ in range(self._extract_worker_count):
            await self._extract_queue.put(None)
        await self._reconcile_queue.put(None)
        await self._snapshot_queue.put(None)

        for worker in [*self._extract_workers, self._reconcile_worker, self._snapshot_worker]:
            if worker is None:
                continue
            try:
                await worker
            except asyncio.CancelledError:
                pass

        self._extract_workers = []
        self._flush_worker = None
        self._reconcile_worker = None
        self._snapshot_worker = None

    async def enqueue_event(self, event: MemoryEvent) -> bool:
        if self._cognition_store is None or not event.cognition_eligible:
            self._stats.extract_skipped += 1
            return False

        max_events, max_estimated_tokens = self._resolve_batch_limits(event)
        owner_key = None
        if isinstance(event.metadata_json, dict):
            owner_key = event.metadata_json.get("l2_batch_owner")
        bucket_key = build_l2_batch_bucket_key(
            session_id=event.session_id,
            user_id=event.user_id,
            owner_key=str(owner_key) if owner_key is not None else None,
        )
        if bucket_key is None:
            await self._enqueue_extract_job(
                L2BatchJob(
                    job_id=f"event:{event.event_id}",
                    bucket_key=f"event:{event.event_id}",
                    events=[self._serialize_event_for_batch(event)],
                    flush_reason="direct_fallback",
                    estimated_tokens=self._estimate_event_tokens(event.content),
                    session_id=event.session_id,
                    user_id=event.user_id,
                )
            )
            return True

        job_to_flush: L2BatchJob | None = None
        async with self._staging_lock:
            bucket = self._staging_buckets.get(bucket_key)
            if bucket is None:
                bucket = L2PendingBatchBucket.for_owner(
                    session_id=event.session_id,
                    user_id=event.user_id,
                    owner_key=str(owner_key) if owner_key is not None else None,
                    max_events=max_events,
                    max_estimated_tokens=max_estimated_tokens,
                )
                self._staging_buckets[bucket_key] = bucket
            bucket.add_event(
                self._serialize_event_for_batch(event),
                estimated_tokens=self._estimate_event_tokens(event.content),
                max_events=max_events,
                max_estimated_tokens=max_estimated_tokens,
            )
            self._refresh_staging_stats_locked()
            flush_reason = self._flush_reason_for_bucket(bucket)
            if flush_reason is not None:
                job_to_flush = self._build_and_remove_bucket_job_locked(bucket_key=bucket_key, flush_reason=flush_reason)

        if job_to_flush is not None:
            await self._enqueue_extract_job(job_to_flush)
        return True

    async def enqueue_entities(self, entity_ids: list[str]) -> bool:
        normalized = sorted({entity_id.strip() for entity_id in entity_ids if entity_id and entity_id.strip()})
        if not normalized or self._cognition_store is None:
            return False
        await self._reconcile_queue.put(normalized)
        self._stats.reconcile_enqueued += 1
        return True

    async def enqueue_snapshot_refresh(self, entity_ids: list[str]) -> bool:
        normalized = sorted({entity_id.strip() for entity_id in entity_ids if entity_id and entity_id.strip()})
        if not normalized or self._cognition_store is None:
            return False
        await self._snapshot_queue.put(normalized)
        self._stats.snapshot_enqueued += 1
        return True

    async def flush_session(self, session_id: str) -> list[str]:
        """Flush remaining staged events for *session_id* and enqueue a
        comprehensive reconciliation of all entities touched during the session.

        Returns the list of entity_ids scheduled for session-end reconciliation.
        """
        if not session_id or self._cognition_store is None:
            return []

        bucket_key = build_l2_batch_bucket_key(session_id=session_id, user_id=None)
        job: L2BatchJob | None = None
        if bucket_key is not None:
            async with self._staging_lock:
                job = self._build_and_remove_bucket_job_locked(
                    bucket_key=bucket_key, flush_reason="session_end",
                )
        if job is not None:
            await self._enqueue_extract_job(job)

        accumulated = sorted(self._session_touched_entities.pop(session_id, set()))
        if accumulated:
            logger.info(
                "L2 session-end review enqueued",
                session_id=session_id,
                entity_count=len(accumulated),
            )
            expired_count = await self._cognition_store.expire_session_decay_assertions(
                entity_ids=accumulated,
            )
            if expired_count:
                logger.info(
                    "L2 session-end tentative assertions expired",
                    session_id=session_id,
                    expired_count=expired_count,
                )
            await self.enqueue_entities(accumulated)
            await self.enqueue_snapshot_refresh(accumulated)
        return accumulated

    async def flush_all_pending_batches(self) -> int:
        """Flush every currently staged microbatch into extract jobs."""
        if self._cognition_store is None:
            return 0

        jobs: list[L2BatchJob] = []
        async with self._staging_lock:
            for bucket_key in list(self._staging_buckets.keys()):
                job = self._build_and_remove_bucket_job_locked(
                    bucket_key=bucket_key,
                    flush_reason="manual_flush",
                )
                if job is not None:
                    jobs.append(job)

        for job in jobs:
            await self._enqueue_extract_job(job)

        projection_batch_count = await self._claim_pending_projection_jobs(
            limit=self._projection_claim_limit,
            force=True,
        )
        if jobs:
            logger.info("L2 manual microbatch flush enqueued", batch_count=len(jobs))
        if projection_batch_count:
            logger.info(
                "L2 manual durable projection flush enqueued",
                batch_count=projection_batch_count,
            )
        return len(jobs) + int(projection_batch_count)

    def _accumulate_session_entities(
        self, session_id: str | None, entity_ids: list[str],
    ) -> None:
        if not session_id or not entity_ids:
            return
        bucket = self._session_touched_entities.get(session_id)
        if bucket is None:
            bucket = set()
            self._session_touched_entities[session_id] = bucket
        bucket.update(entity_ids)

    def get_statistics(self) -> dict[str, int | bool]:
        return asdict(self._stats)

    async def _run_flush_worker(self) -> None:
        poll_interval = DEFAULT_L2_FLUSH_POLL_INTERVAL_SECONDS
        while self._stats.is_running:
            try:
                await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                break
            await self._claim_pending_projection_jobs()
            await self._flush_ready_buckets()

    async def _claim_pending_projection_jobs(self, *, limit: int | None = None, force: bool = False) -> int:
        if self._cognition_store is None or self._l1_store is None:
            return 0

        await self._cognition_store.requeue_stale_projection_jobs(
            queued_timeout_seconds=self._projection_stale_queued_timeout_seconds,
            running_timeout_seconds=self._projection_stale_running_timeout_seconds,
        )
        claim_limit = max(1, int(limit or self._projection_claim_limit))
        if force:
            claimed_rows = await self._cognition_store.claim_projection_jobs(
                consumer_name=self._projection_consumer_name,
                limit=claim_limit,
            )
        else:
            claimed_rows = await self._cognition_store.claim_ready_projection_jobs(
                consumer_name=self._projection_consumer_name,
                limit=claim_limit,
            )
        if not claimed_rows:
            return 0

        claimed_rows = sorted(
            claimed_rows,
            key=lambda item: (
                float(item.get("created_at", 0.0) or 0.0),
                str(item.get("event_id", "")),
            ),
        )
        jobs, missing_event_ids = await self._build_extract_jobs_from_projection_rows(claimed_rows)
        if missing_event_ids:
            await self._cognition_store.fail_projection_jobs(
                missing_event_ids,
                error_text="l1_event_not_found",
                requeue=False,
            )
            logger.warning(
                "L2 projection jobs referenced missing L1 events",
                event_ids=missing_event_ids,
            )

        for job in jobs:
            await self._enqueue_extract_job(job)
        return len(jobs)

    async def _flush_ready_buckets(self) -> None:
        jobs: list[L2BatchJob] = []
        async with self._staging_lock:
            for bucket_key, bucket in list(self._staging_buckets.items()):
                if bucket.is_flushing or not bucket.events:
                    continue
                flush_reason = self._flush_reason_for_bucket(bucket)
                if flush_reason not in {None, "interval_elapsed"}:
                    continue
                if flush_reason == "interval_elapsed":
                    job = self._build_and_remove_bucket_job_locked(bucket_key=bucket_key, flush_reason=flush_reason)
                    if job is not None:
                        jobs.append(job)
        for job in jobs:
            await self._enqueue_extract_job(job)

    async def _flush_all_buckets(self, *, flush_reason: str) -> None:
        jobs: list[L2BatchJob] = []
        async with self._staging_lock:
            for bucket_key in list(self._staging_buckets.keys()):
                job = self._build_and_remove_bucket_job_locked(bucket_key=bucket_key, flush_reason=flush_reason)
                if job is not None:
                    jobs.append(job)
        for job in jobs:
            await self._enqueue_extract_job(job)

    async def _enqueue_extract_job(self, job: L2BatchJob) -> None:
        await self._extract_queue.put(job)
        self._stats.extract_enqueued += 1

    async def _build_extract_jobs_from_projection_rows(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[list[L2BatchJob], list[str]]:
        jobs: list[L2BatchJob] = []
        missing_event_ids: list[str] = []
        buckets: dict[str, L2PendingBatchBucket] = {}

        for row in rows:
            event_id = str(row.get("event_id", "")).strip()
            if not event_id:
                continue
            event = await self._l1_store.get_memory_event(event_id) if self._l1_store is not None else None
            if event is None:
                missing_event_ids.append(event_id)
                continue

            max_events, max_estimated_tokens = self._resolve_batch_limits(event)
            owner_key = row.get("effective_batch_owner")
            if owner_key is None and isinstance(event.metadata_json, dict):
                owner_key = event.metadata_json.get("l2_batch_owner")
            if owner_key is None:
                owner_key = row.get("batch_owner")
            normalized_owner_key = str(owner_key) if owner_key is not None else None
            bucket_key = build_l2_batch_bucket_key(
                session_id=event.session_id,
                user_id=event.user_id,
                owner_key=normalized_owner_key,
            )
            if bucket_key is None:
                direct_job = L2BatchJob(
                    job_id=f"projection:{event.event_id}",
                    bucket_key=f"event:{event.event_id}",
                    events=[self._serialize_event_for_batch(event)],
                    flush_reason="projection_direct",
                    estimated_tokens=self._estimate_event_tokens(event.content),
                    session_id=event.session_id,
                    user_id=event.user_id,
                )
                self._record_batch_flush(direct_job, flush_reason=direct_job.flush_reason)
                jobs.append(direct_job)
                continue

            bucket = buckets.get(bucket_key)
            if bucket is None:
                bucket = L2PendingBatchBucket.for_owner(
                    session_id=event.session_id,
                    user_id=event.user_id,
                    owner_key=normalized_owner_key,
                    max_events=max_events,
                    max_estimated_tokens=max_estimated_tokens,
                )
                buckets[bucket_key] = bucket
            bucket.add_event(
                self._serialize_event_for_batch(event),
                estimated_tokens=self._estimate_event_tokens(event.content),
                max_events=max_events,
                max_estimated_tokens=max_estimated_tokens,
            )
            flush_reason = self._flush_reason_for_bucket(bucket)
            if flush_reason is not None:
                jobs.append(self._build_projection_bucket_job(bucket, flush_reason=flush_reason))
                buckets.pop(bucket_key, None)

        for bucket in buckets.values():
            jobs.append(self._build_projection_bucket_job(bucket, flush_reason="projection_ready"))
        return jobs, missing_event_ids

    def _build_and_remove_bucket_job_locked(self, *, bucket_key: str, flush_reason: str) -> L2BatchJob | None:
        bucket = self._staging_buckets.pop(bucket_key, None)
        if bucket is None or not bucket.events:
            self._refresh_staging_stats_locked()
            return None
        bucket.is_flushing = True
        job = bucket.build_job(flush_reason=flush_reason)
        self._record_batch_flush(job, flush_reason=flush_reason)
        self._refresh_staging_stats_locked()
        return job

    def _build_projection_bucket_job(
        self,
        bucket: L2PendingBatchBucket,
        *,
        flush_reason: str,
    ) -> L2BatchJob:
        job = bucket.build_job(
            flush_reason=flush_reason,
            job_id=f"projection:{bucket.bucket_key}:{int(bucket.newest_event_timestamp * 1000)}",
        )
        self._record_batch_flush(job, flush_reason=flush_reason)
        return job

    def _record_batch_flush(self, job: L2BatchJob, *, flush_reason: str) -> None:
        self._stats.batch_flush_count += 1
        self._increment_bucket(self._stats.batch_flush_by_reason, flush_reason)
        previous_flushes = self._stats.batch_flush_count - 1
        self._stats.avg_batch_event_count = self._rolling_average(
            current_average=self._stats.avg_batch_event_count,
            previous_count=previous_flushes,
            new_value=float(len(job.events)),
        )
        self._stats.avg_batch_estimated_tokens = self._rolling_average(
            current_average=self._stats.avg_batch_estimated_tokens,
            previous_count=previous_flushes,
            new_value=float(job.estimated_tokens),
        )

    def _flush_reason_for_bucket(self, bucket: L2PendingBatchBucket) -> str | None:
        max_events = bucket.max_events or DEFAULT_L2_MAX_EVENTS_PER_BATCH
        max_estimated_tokens = bucket.max_estimated_tokens or DEFAULT_L2_MAX_ESTIMATED_TOKENS_PER_BATCH
        if len(bucket.events) >= max_events:
            return "max_events"
        if bucket.estimated_tokens >= max_estimated_tokens:
            return "token_cap"
        if not bucket.events:
            return None
        if self._batch_flush_interval_seconds <= 0:
            return "interval_elapsed"
        oldest_age_seconds = max(0.0, time.time() - bucket.created_at)
        if oldest_age_seconds >= float(self._batch_flush_interval_seconds):
            return "interval_elapsed"
        return None

    def _refresh_staging_stats_locked(self) -> None:
        self._stats.active_bucket_count = len(self._staging_buckets)
        self._stats.pending_staged_event_count = sum(len(bucket.events) for bucket in self._staging_buckets.values())

    def _serialize_event_for_batch(self, event: MemoryEvent) -> dict[str, Any]:
        payload = event.to_dict()
        payload["memory_domain"] = event.memory_domain.label
        payload["ingest_target"] = event.ingest_target.label
        payload["tom_depth"] = event.tom_depth.label
        payload["retention_class"] = event.retention_class.label
        return payload

    def _estimate_event_tokens(self, text: str) -> int:
        normalized = str(text or "").strip()
        return max(1, len(normalized) // 4) if normalized else 1

    def _resolve_batch_limits(self, event: MemoryEvent) -> tuple[int | None, int | None]:
        if not isinstance(event.metadata_json, dict):
            return (None, None)
        max_events = event.metadata_json.get("l2_batch_max_events")
        max_estimated_tokens = event.metadata_json.get("l2_batch_max_estimated_tokens")
        resolved_max_events = max(1, int(max_events)) if max_events is not None else None
        resolved_max_tokens = (
            max(1, int(max_estimated_tokens))
            if max_estimated_tokens is not None
            else None
        )
        return (resolved_max_events, resolved_max_tokens)

    def _rolling_average(self, *, current_average: float, previous_count: int, new_value: float) -> float:
        if previous_count <= 0:
            return new_value
        return ((current_average * previous_count) + new_value) / float(previous_count + 1)

    async def _run_extract_worker(self) -> None:
        if self._cognition_store is None:
            return

        while True:
            job = await self._extract_queue.get()
            try:
                if job is None:
                    break
                logger.info(
                    "L2 extract started",
                    job_id=job.job_id,
                    batch_key=job.bucket_key,
                    event_ids=job.event_ids,
                    flush_reason=job.flush_reason,
                    queue_size=self._extract_queue.qsize(),
                )
                if job.event_ids:
                    transitioned = await self._cognition_store.mark_projection_jobs_running(
                        job.event_ids,
                        consumer_name=self._projection_consumer_name,
                    )
                    if transitioned == 0:
                        self._stats.extract_skipped += 1
                        logger.info(
                            "L2 extract skipped (stale batch)",
                            job_id=job.job_id,
                            event_ids=job.event_ids,
                            queue_size=self._extract_queue.qsize(),
                        )
                        continue
                result = await self._extract_and_persist(job)
                if job.event_ids:
                    await self._cognition_store.complete_projection_jobs(job.event_ids)
                self._stats.extract_completed += 1
                if result.get("skipped"):
                    self._stats.extract_skipped += 1
                    logger.info(
                        "L2 extract skipped",
                        job_id=job.job_id,
                        event_ids=job.event_ids,
                        evidence_class=result.get("evidence_class"),
                        skip_reason=result.get("skip_reason"),
                        queue_size=self._extract_queue.qsize(),
                    )
                else:
                    logger.info(
                        "L2 extract completed",
                        job_id=job.job_id,
                        event_ids=job.event_ids,
                        evidence_class=result.get("evidence_class"),
                        profile_id=result.get("profile_id"),
                        mention_count=int(result.get("mention_count", 0)),
                        graph_candidate_count=int(result.get("graph_candidate_count", 0)),
                        assertion_candidate_count=int(result.get("assertion_candidate_count", 0)),
                        rejected_graph_candidate_count=int(result.get("rejected_graph_candidate_count", 0)),
                        rejected_assertion_candidate_count=int(result.get("rejected_assertion_candidate_count", 0)),
                        relation_count=int(result["relation_count"]),
                        assertion_count=int(result["assertion_count"]),
                        contradiction_hint_count=int(result.get("contradiction_hint_count", 0)),
                        touched_entity_count=len(result.get("touched_entity_ids", [])),
                        queue_size=self._extract_queue.qsize(),
                    )
                self._stats.relations_written += int(result["relation_count"])
                self._stats.assertions_written += int(result["assertion_count"])
                touched_entity_ids = result.get("touched_entity_ids", [])
                if isinstance(touched_entity_ids, list) and touched_entity_ids:
                    self._accumulate_session_entities(job.session_id, touched_entity_ids)
                    await self.enqueue_entities(touched_entity_ids)
                snapshot_refresh_entity_ids = result.get("snapshot_refresh_entity_ids", [])
                if isinstance(snapshot_refresh_entity_ids, list) and snapshot_refresh_entity_ids:
                    await self.enqueue_snapshot_refresh(snapshot_refresh_entity_ids)
                # ── Episode candidate formation ──────────────────
                if self._cognition_store is not None and job.event_ids and not result.get("skipped"):
                    try:
                        candidate_jobs = [
                            EpisodeCandidateJob(
                                event_id=eid,
                                event_timestamp=float(evt.get("timestamp", 0.0) or 0.0),
                                entity_ids=touched_entity_ids if isinstance(touched_entity_ids, list) else [],
                            )
                            for eid, evt in zip(job.event_ids, job.events)
                        ]
                        if candidate_jobs:
                            await assign_events_to_episode(self._cognition_store, candidate_jobs)
                    except Exception:
                        logger.debug("Episode candidate formation failed", exc_info=True)
            except Exception as exc:
                if self._cognition_store is not None and job is not None and job.event_ids:
                    await self._cognition_store.fail_projection_jobs(
                        job.event_ids,
                        error_text=str(exc),
                        requeue=True,
                    )
                self._stats.extract_failed += 1
                logger.exception(
                    "L2 extract failed",
                    job_id=getattr(job, "job_id", None),
                    event_ids=getattr(job, "event_ids", []),
                    queue_size=self._extract_queue.qsize(),
                )
            finally:
                self._extract_queue.task_done()

    async def _run_reconcile_worker(self) -> None:
        while True:
            entity_ids = await self._reconcile_queue.get()
            try:
                if entity_ids is None:
                    break
                logger.info(
                    "L2 reconcile started",
                    entity_ids=entity_ids,
                    queue_size=self._reconcile_queue.qsize(),
                )
                snapshot_candidates: set[str] = set()
                total_outcomes = 0
                if self._cognition_store is not None:
                    for entity_id in entity_ids:
                        outcomes = await self._cognition_store.reconcile_entity(
                            entity_id=entity_id,
                            entity_type=self._entity_type_from_id(entity_id),
                            evidence_timestamps=await self._load_evidence_timestamps(entity_id),
                        )
                        total_outcomes += len(outcomes)
                        if outcomes:
                            snapshot_candidates.add(entity_id)
                            await self._emit_state_change_insight(
                                entity_id=entity_id,
                                entity_type=self._entity_type_from_id(entity_id),
                                outcomes=outcomes,
                            )
                if snapshot_candidates:
                    await self.enqueue_snapshot_refresh(sorted(snapshot_candidates))
                self._stats.reconcile_completed += 1
                logger.info(
                    "L2 reconcile completed",
                    entity_ids=entity_ids,
                    outcome_count=total_outcomes,
                    snapshot_candidate_count=len(snapshot_candidates),
                    queue_size=self._reconcile_queue.qsize(),
                )
            except Exception:
                self._stats.reconcile_failed += 1
                logger.exception(
                    "L2 reconcile failed",
                    entity_ids=entity_ids,
                    queue_size=self._reconcile_queue.qsize(),
                )
            finally:
                self._reconcile_queue.task_done()

    async def _emit_state_change_insight(
        self,
        *,
        entity_id: str,
        entity_type: str,
        outcomes: list[ReconciledTraitOutcome],
    ) -> None:
        if self._state_change_callback is None or not outcomes:
            return
        try:
            await self._state_change_callback(entity_id, entity_type, outcomes)
        except Exception:
            logger.exception(
                "L2 state change insight callback failed",
                entity_id=entity_id,
                entity_type=entity_type,
                outcome_count=len(outcomes),
            )

    async def _emit_active_entities(
        self,
        *,
        event: MemoryEvent,
        focal_entities: list[L2FocalEntityRef],
    ) -> None:
        if self._active_entity_callback is None or not focal_entities:
            return
        self_entity_id = self._resolve_self_entity_id(event)
        filtered_entities = [
            entity
            for entity in focal_entities
            if entity.entity_id and entity.entity_id != self_entity_id
        ]
        if not filtered_entities:
            return
        try:
            await self._active_entity_callback(event, filtered_entities)
        except Exception:
            logger.exception(
                "L2 active entity callback failed",
                event_id=event.event_id,
                session_id=event.session_id,
                entity_ids=[entity.entity_id for entity in filtered_entities],
            )

    async def _run_snapshot_worker(self) -> None:
        while True:
            entity_ids = await self._snapshot_queue.get()
            try:
                if entity_ids is None:
                    break
                logger.info(
                    "L2 snapshot started",
                    entity_ids=entity_ids,
                    queue_size=self._snapshot_queue.qsize(),
                )
                refreshed_count = 0
                if self._cognition_store is not None:
                    for entity_id in entity_ids:
                        snapshot = await self._cognition_store.refresh_entity_snapshot(
                            entity_id=entity_id,
                            entity_type=self._entity_type_from_id(entity_id),
                        )
                        if snapshot is not None:
                            refreshed_count += 1
                self._stats.snapshot_completed += 1
                logger.info(
                    "L2 snapshot completed",
                    entity_ids=entity_ids,
                    refreshed_count=refreshed_count,
                    queue_size=self._snapshot_queue.qsize(),
                )
            except Exception:
                self._stats.snapshot_failed += 1
                logger.exception(
                    "L2 snapshot failed",
                    entity_ids=entity_ids,
                    queue_size=self._snapshot_queue.qsize(),
                )
            finally:
                self._snapshot_queue.task_done()

    async def _extract_and_persist(self, job: L2BatchJob) -> dict[str, Any]:
        if self._cognition_store is None:
            return {"relation_count": 0, "assertion_count": 0, "touched_entity_ids": [], "skipped": True}

        stored_events = await self._load_batch_events(job)
        if not stored_events:
            return {
                "relation_count": 0,
                "assertion_count": 0,
                "touched_entity_ids": [],
                "skipped": True,
                "skip_reason": "empty_batch",
                "evidence_class": None,
                "contradiction_hint_count": 0,
            }

        eligible_events: list[tuple[MemoryEvent, Any, Any]] = []
        for stored_event in stored_events:
            classification = classify_event_evidence(stored_event)
            self._increment_bucket(self._stats.extract_by_evidence_class, classification.evidence_class)
            logger.debug(
                "L2 evidence classified",
                event_id=stored_event.event_id,
                evidence_class=classification.evidence_class,
                grounding_type=classification.grounding_type,
                semantic_owner=classification.semantic_owner,
                originality_type=classification.originality_type,
                source_event_ids=classification.source_event_ids,
            )
            policy = resolve_l2_policy(classification)
            logger.debug(
                "L2 policy resolved",
                event_id=stored_event.event_id,
                evidence_class=classification.evidence_class,
                allow_entity_extraction=policy.allow_entity_extraction,
                allow_graph_write=policy.allow_graph_write,
                allow_assertion_write=policy.allow_assertion_write,
                allow_snapshot_impact=policy.allow_snapshot_impact,
                graph_scope=policy.graph_scope,
                assertion_scope=policy.assertion_scope,
                skip_reason=policy.skip_reason,
            )
            if policy.allow_graph_write or policy.allow_assertion_write:
                eligible_events.append((stored_event, classification, policy))

        if not eligible_events:
            classification = classify_event_evidence(stored_events[-1])
            policy = resolve_l2_policy(classification)
            if policy.skip_reason:
                self._increment_bucket(self._stats.skip_by_reason, policy.skip_reason)
            return {
                "relation_count": 0,
                "assertion_count": 0,
                "touched_entity_ids": [],
                "skipped": True,
                "skip_reason": policy.skip_reason or "no_eligible_events",
                "evidence_class": classification.evidence_class,
                "contradiction_hint_count": 0,
            }

        stored_event, classification, policy = eligible_events[-1]
        batch_event_ids = [item.event_id for item, _, _ in eligible_events]
        if not policy.allow_graph_write and not policy.allow_assertion_write:
            if policy.skip_reason:
                self._increment_bucket(self._stats.skip_by_reason, policy.skip_reason)
            return {
                "relation_count": 0,
                "assertion_count": 0,
                "touched_entity_ids": [],
                "skipped": True,
                "skip_reason": policy.skip_reason,
                "evidence_class": classification.evidence_class,
                "contradiction_hint_count": 0,
            }

        context_messages = (
            await self._load_context_messages(stored_event, exclude_event_ids=batch_event_ids)
            if policy.allow_entity_extraction or policy.allow_assertion_write or policy.allow_graph_write
            else []
        )
        history_contexts = (
            await self._load_history_contexts(
                anchor_event=stored_event,
                batch_events=[item[0] for item in eligible_events],
                exclude_event_ids=batch_event_ids,
            )
            if policy.allow_entity_extraction or policy.allow_assertion_write or policy.allow_graph_write
            else []
        )
        extraction_profile = resolve_extraction_profile(stored_event)
        self_entity_id = self._resolve_self_entity_id(stored_event)

        # Build event window
        event_window = L2EventWindow(
            event_ids=batch_event_ids,
            events=[self._serialize_event_for_batch(item[0]) for item in eligible_events],
            texts=[item[0].content for item in eligible_events],
            context_texts=[msg.get("content", "") for msg in context_messages if msg.get("content", "").strip()],
            history_contexts=history_contexts,
            summary=L2EventWindowSummary(
                event_count=len(eligible_events),
                session_id=stored_event.session_id,
                user_id=stored_event.user_id,
                history_context_count=len(history_contexts),
            ),
        )
        focal_subject = {
            "entity_ref": self_entity_id,
            "entity_type": "user" if self_entity_id else None,
        }

        # Load existing entities from catalog for Phase 1 resolution hints
        existing_entities: list[dict[str, Any]] = []
        if self._entity_catalog is not None:
            existing_entities = await self._entity_catalog.list_entities(limit=30)

        # Inject structured entity hints as Phase 1 context (not materialized)
        self._inject_structured_entity_hints(stored_event, existing_entities)

        # ── Pre-Phase 1: Direct-write admissible structured graph hints ──
        catalog_name_index = await self._build_catalog_name_index()
        direct_write_candidates, _direct_rejected = self._build_structured_graph_candidates(
            event=stored_event,
            profile=extraction_profile,
            policy=policy,
            evidence_event_ids=batch_event_ids,
            catalog_name_index=catalog_name_index,
        )
        direct_write_count = 0
        if direct_write_candidates and self._cognition_store is not None:
            for candidate in direct_write_candidates:
                await self._cognition_store.upsert_knowledge_edge(**candidate)
                direct_write_count += 1
            logger.debug(
                "L2 structured hints direct-written before Phase 1",
                event_id=stored_event.event_id,
                direct_write_count=direct_write_count,
            )

        # ── Phase 1: Extract & Resolve ──
        logger.info(
            "L2 Phase 1 extraction started",
            event_id=stored_event.event_id,
            profile_id=extraction_profile.profile_id,
            context_message_count=len(context_messages),
            history_context_count=len(history_contexts),
            existing_entity_count=len(existing_entities),
        )

        phase1_result = await self._llm_service.extract_phase1(
            event_window=event_window,
            focal_subject=focal_subject,
            existing_entities=existing_entities,
            context_messages=context_messages,
            extraction_instructions=extraction_profile.extraction_instructions,
        )
        # Structured graph hints are already direct-written before Phase 1 (T3).
        # They will appear in existing_graph_edges loaded for Phase 2.

        # Register Phase 1 entities in the entity catalog
        resolved_mentions: list[ResolvedEntityMention] = []
        if policy.allow_entity_extraction and phase1_result.entities:
            resolved_mentions = await self._resolve_phase1_entities(
                stored_event,
                phase1_result,
                evidence_event_ids=batch_event_ids,
                allowed_entity_types=extraction_profile.allowed_entity_types,
            )

        logger.debug(
            "L2 Phase 1 completed",
            event_id=stored_event.event_id,
            entity_count=len(phase1_result.entities),
            fact_claim_count=len(phase1_result.fact_claims),
            resolved_ref_count=len(phase1_result.resolved_refs),
            resolved_mention_count=len(resolved_mentions),
        )

        # ── Write L1 event–entity linkage for entity co-occurrence retrieval ──
        if resolved_mentions and self._l1_store is not None:
            entity_mappings = [
                (eid, m.resolved_entity_id, m.entity_type, m.confidence)
                for m in resolved_mentions
                if m.resolved_entity_id
                for eid in batch_event_ids
            ]
            if entity_mappings:
                try:
                    await self._l1_store.write_event_entities(entity_mappings)
                except Exception as exc:
                    logger.warning(
                        "Failed to write l1_event_entities",
                        event_id=stored_event.event_id,
                        exc_info=exc,
                    )

        # ── Build entity-scoped semantic edges (async, best-effort) ──
        if resolved_mentions and self._semantic_edge_builder is not None:
            resolved_entity_ids = list({
                m.resolved_entity_id
                for m in resolved_mentions
                if m.resolved_entity_id
            })
            if resolved_entity_ids:
                try:
                    sem_edge_count = await self._semantic_edge_builder.build_edges_for_event(
                        event_id=stored_event.event_id,
                        entity_ids=resolved_entity_ids,
                        observed_at=float(stored_event.timestamp),
                    )
                    if sem_edge_count > 0:
                        logger.debug(
                            "Entity-scoped semantic edges created",
                            event_id=stored_event.event_id,
                            edge_count=sem_edge_count,
                        )
                except Exception as exc:
                    logger.warning(
                        "Entity-scoped semantic edge building failed",
                        event_id=stored_event.event_id,
                        exc_info=exc,
                    )

        if not phase1_result.has_content:
            # Even when Phase 1 is empty, persist any structured
            # facets that accompanied the direct-written graph hints.
            facet_candidates = self._build_structured_facet_candidates(
                event=stored_event,
                evidence_event_ids=batch_event_ids,
            )
            facet_count = 0
            if facet_candidates and self._cognition_store is not None:
                for candidate in facet_candidates:
                    await self._cognition_store.upsert_entity_facet(**candidate)
                    facet_count += 1

            logger.info(
                "L2 Phase 1 returned empty result, skipping Phase 2",
                event_id=stored_event.event_id,
                profile_id=extraction_profile.profile_id,
                evidence_class=classification.evidence_class,
                direct_write_count=direct_write_count,
                facet_count=facet_count,
            )
            return {
                "relation_count": direct_write_count,
                "assertion_count": 0,
                "touched_entity_ids": [],
                "snapshot_refresh_entity_ids": [],
                "skipped": False,
                "evidence_class": classification.evidence_class,
                "profile_id": extraction_profile.profile_id,
                "mention_count": len(phase1_result.entities),
                "direct_write_count": direct_write_count,
                "graph_candidate_count": 0,
                "assertion_candidate_count": 0,
                "rejected_graph_candidate_count": 0,
                "rejected_assertion_candidate_count": 0,
                "contradiction_hint_count": 0,
                "conflict_arbitration_decision": None,
            }

        # ── Load existing graph context for Phase 2 ──
        existing_graph_edges: list[dict[str, Any]] = []
        existing_assertions: list[dict[str, Any]] = []
        focal_entities = self._build_focal_entities(stored_event, resolved_mentions)
        await self._emit_active_entities(event=stored_event, focal_entities=focal_entities)
        if self._cognition_store is not None:
            existing_graph_edges, existing_assertions = await self._load_existing_graph_context(focal_entities)

        # ── Fast-track: skip Phase 2 when Phase 1 output is simple ──
        if self._can_fast_track(
            phase1_result=phase1_result,
            resolved_mentions=resolved_mentions,
            existing_graph_edges=existing_graph_edges,
            profile=extraction_profile,
            policy=policy,
        ):
            fast_track_candidates = self._fast_track_claims_to_candidates(
                phase1_result=phase1_result,
                event=stored_event,
                evidence_event_ids=batch_event_ids,
                resolved_mentions=resolved_mentions,
                catalog_name_index=catalog_name_index,
                profile=extraction_profile,
            )
            facet_candidates = self._build_structured_facet_candidates(
                event=stored_event,
                evidence_event_ids=batch_event_ids,
            )
            relation_count = 0
            facet_count = 0
            if self._cognition_store is not None:
                for candidate in fast_track_candidates:
                    await self._cognition_store.upsert_knowledge_edge(**candidate)
                    relation_count += 1
                for candidate in facet_candidates:
                    await self._cognition_store.upsert_entity_facet(**candidate)
                    facet_count += 1
            touched_entity_ids = self._collect_touched_entities(fast_track_candidates, [])
            logger.info(
                "L2 fast-track: skipped Phase 2",
                event_id=stored_event.event_id,
                profile_id=extraction_profile.profile_id,
                relation_count=relation_count,
                direct_write_count=direct_write_count,
                facet_count=facet_count,
            )
            return {
                "relation_count": relation_count,
                "assertion_count": 0,
                "touched_entity_ids": touched_entity_ids,
                "snapshot_refresh_entity_ids": [],
                "skipped": False,
                "evidence_class": classification.evidence_class,
                "profile_id": extraction_profile.profile_id,
                "mention_count": len(phase1_result.entities),
                "direct_write_count": direct_write_count,
                "corroborate_count": 0,
                "graph_candidate_count": len(fast_track_candidates),
                "assertion_candidate_count": 0,
                "rejected_graph_candidate_count": 0,
                "rejected_assertion_candidate_count": 0,
                "contradiction_hint_count": 0,
                "conflict_arbitration_decision": None,
                "fast_tracked": True,
            }

        # ── Phase 2: Integrate & Reason ──
        logger.info(
            "L2 Phase 2 integration started",
            event_id=stored_event.event_id,
            existing_edge_count=len(existing_graph_edges),
            existing_assertion_count=len(existing_assertions),
        )

        phase2_result = await self._llm_service.integrate_phase2(
            phase1_result=phase1_result,
            existing_graph_edges=existing_graph_edges,
            existing_assertions=existing_assertions,
            event_window=event_window,
            focal_subject=focal_subject,
        )

        # ── Validate and prepare Phase 2 outputs ──
        catalog_name_index = await self._build_catalog_name_index()
        graph_candidates, corroborate_targets, rejected_graph_candidate_count = self._validate_phase2_graph_edges(
            event=stored_event,
            profile=extraction_profile,
            policy=policy,
            resolved_mentions=resolved_mentions,
            evidence_event_ids=batch_event_ids,
            phase2_edges=phase2_result.graph_edges,
            catalog_name_index=catalog_name_index,
        )
        facet_candidates = self._build_structured_facet_candidates(
            event=stored_event,
            evidence_event_ids=batch_event_ids,
        )

        # Include direct-written candidates in assertion dedup context
        # but do NOT rebuild or re-persist them (already written before Phase 1)
        assertion_dedup_context = self._merge_graph_candidates(
            graph_candidates,
            direct_write_candidates,
        )

        assertion_candidates, rejected_assertion_candidate_count = self._validate_phase2_assertions(
            event=stored_event,
            profile=extraction_profile,
            policy=policy,
            graph_candidates=assertion_dedup_context,
            default_event_ids=batch_event_ids,
            phase2_assertions=phase2_result.assertion_candidates,
        )

        # Convert Phase 2 contradiction hints to ContradictionHint
        contradiction_hints = self._convert_phase2_contradiction_hints(phase2_result.contradiction_hints)

        logger.info(
            "L2 Phase 2 candidate validation completed",
            event_id=stored_event.event_id,
            profile_id=extraction_profile.profile_id,
            graph_candidate_count=len(graph_candidates),
            assertion_candidate_count=len(assertion_candidates),
            rejected_graph_candidate_count=rejected_graph_candidate_count,
            rejected_assertion_candidate_count=rejected_assertion_candidate_count,
            contradiction_hint_count=len(contradiction_hints),
        )

        # Conflict arbitration for severe contradictions (uses CORE LLM scenario)
        conflict_arbitration: L2ConflictArbitrationResult | None = None
        if contradiction_hints and (graph_candidates or assertion_candidates):
            conflict_arbitration = await self._arbitrate_conflicting_candidates(
                anchor_event=stored_event,
                batch_events=[item[0] for item in eligible_events],
                graph_candidates=graph_candidates,
                assertion_candidates=assertion_candidates,
                contradiction_hints=contradiction_hints,
            )
            arbitration_decision = conflict_arbitration.decision if conflict_arbitration is not None else None
            if arbitration_decision == "keep_existing":
                logger.info(
                    "L2 conflict arbitration kept existing records",
                    event_id=stored_event.event_id,
                    decision="keep_existing",
                    severe_hint_count=len(self._severe_contradiction_hints(contradiction_hints)),
                )
                graph_candidates = []
                assertion_candidates = []
                contradiction_hints = self._rewrite_hints_for_keep_existing(
                    contradiction_hints=contradiction_hints,
                    conflict_arbitration=conflict_arbitration,
                )
            elif arbitration_decision == "mark_evolution":
                contradiction_hints = self._rewrite_hints_for_evolution(
                    contradiction_hints=contradiction_hints,
                    conflict_arbitration=conflict_arbitration,
                )

        relation_count = 0
        corroborate_count = 0
        facet_count = 0
        assertion_count = 0

        # Acquire per-entity locks before persisting to prevent concurrent
        # workers from interleaving read-then-write sequences on the same entity.
        persist_entity_ids = sorted(
            {str(c.get("subject_id", "")) for c in graph_candidates + direct_write_candidates if c.get("subject_id")}
            | {str(c.get("object_id", "")) for c in graph_candidates + direct_write_candidates if c.get("object_id")}
            | {str(c.get("entity_id", "")) for c in assertion_candidates if c.get("entity_id")}
        )
        entity_locks = await self._acquire_entity_locks(persist_entity_ids)
        try:
            for candidate in graph_candidates:
                await self._cognition_store.upsert_knowledge_edge(**candidate)
                relation_count += 1

            for target in corroborate_targets:
                updated = await self._cognition_store.corroborate_edge(**target)
                if updated:
                    corroborate_count += 1

            for candidate in facet_candidates:
                await self._cognition_store.upsert_entity_facet(**candidate)
                facet_count += 1

            for candidate in assertion_candidates:
                await self._cognition_store.upsert_assertion_candidate(candidate)
                assertion_count += 1

            for hint in contradiction_hints:
                await self._cognition_store.apply_contradiction_hint(hint)
        finally:
            for lock in entity_locks:
                lock.release()

        logger.info(
            "L2 persistence completed",
            event_id=stored_event.event_id,
            profile_id=extraction_profile.profile_id,
            relation_count=relation_count,
            corroborate_count=corroborate_count,
            facet_count=facet_count,
            assertion_count=assertion_count,
            contradiction_hint_count=len(contradiction_hints),
            conflict_arbitration_decision=conflict_arbitration.decision if conflict_arbitration is not None else None,
        )

        conflict_arbitration_decision = conflict_arbitration.decision if conflict_arbitration is not None else None
        touched_entity_ids = self._collect_touched_entities(
            graph_candidates + direct_write_candidates, assertion_candidates
        )
        # Also include focal entity if contradiction hints were applied (triggers reconcile → L3 summaries)
        if contradiction_hints:
            self_entity_id = self._resolve_self_entity_id(stored_event)
            if self_entity_id and self_entity_id not in touched_entity_ids:
                touched_entity_ids.append(self_entity_id)
        snapshot_refresh_entity_ids = (
            touched_entity_ids
            if conflict_arbitration_decision == "mark_evolution" and relation_count > 0
            else []
        )

        return {
            "relation_count": relation_count,
            "assertion_count": assertion_count,
            "touched_entity_ids": touched_entity_ids,
            "snapshot_refresh_entity_ids": snapshot_refresh_entity_ids,
            "skipped": False,
            "evidence_class": classification.evidence_class,
            "profile_id": extraction_profile.profile_id,
            "mention_count": len(phase1_result.entities),
            "resolved_context_ref_count": len(phase1_result.resolved_refs),
            "graph_candidate_count": len(graph_candidates),
            "direct_write_count": direct_write_count,
            "corroborate_count": corroborate_count,
            "assertion_candidate_count": len(assertion_candidates),
            "rejected_graph_candidate_count": rejected_graph_candidate_count,
            "rejected_assertion_candidate_count": rejected_assertion_candidate_count,
            "contradiction_hint_count": len(contradiction_hints),
            "conflict_arbitration_decision": conflict_arbitration_decision,
        }

    async def _load_stored_event(self, event: MemoryEvent) -> MemoryEvent:
        if self._l1_store is None:
            return event
        stored_event = await self._l1_store.get_memory_event(event.event_id)
        if stored_event is None:
            return event
        return stored_event

    async def _acquire_entity_locks(self, entity_ids: list[str]) -> list[asyncio.Lock]:
        """Acquire per-entity locks in sorted order to prevent deadlocks.

        Returns the list of acquired locks (caller must release them).
        """
        locks: list[asyncio.Lock] = []
        for eid in sorted(entity_ids):
            async with self._entity_locks_guard:
                lock = self._entity_locks.get(eid)
                if lock is None:
                    lock = asyncio.Lock()
                    self._entity_locks[eid] = lock
            await lock.acquire()
            locks.append(lock)
        return locks

    async def _load_batch_events(self, job: L2BatchJob) -> list[MemoryEvent]:
        batch_events: list[MemoryEvent] = []
        for payload in job.events:
            event = self._deserialize_batch_event(payload)
            if event is None:
                continue
            batch_events.append(await self._load_stored_event(event))
        return batch_events

    def _deserialize_batch_event(self, payload: dict[str, Any]) -> MemoryEvent | None:
        from ..event_contracts import IngestTarget, MemoryDomain, RetentionClass, TomDepth

        if not isinstance(payload, dict):
            return None
        event_id = self._non_empty_text(payload.get("event_id"))
        if event_id is None:
            return None
        return MemoryEvent(
            event_id=event_id,
            correlation_id=str(payload.get("correlation_id") or ""),
            timestamp=float(payload.get("timestamp", 0.0) or 0.0),
            created_at=float(payload.get("created_at", payload.get("timestamp", 0.0)) or 0.0),
            event_type=str(payload.get("event_type") or ""),
            source=str(payload.get("source") or "unknown"),
            source_item_id=self._non_empty_text(payload.get("source_item_id")),
            memory_domain=MemoryDomain.from_value(payload.get("memory_domain", "user_authored")),
            ingest_target=IngestTarget.from_value(payload.get("ingest_target", "l1_only")),
            cognition_eligible=bool(payload.get("cognition_eligible", True)),
            tom_depth=TomDepth.from_value(payload.get("tom_depth", "topology_only")),
            retention_class=RetentionClass.from_value(payload.get("retention_class", "compressible")),
            session_id=self._non_empty_text(payload.get("session_id")),
            turn_id=self._non_empty_text(payload.get("turn_id")),
            user_id=self._non_empty_text(payload.get("user_id")),
            task_id=self._non_empty_text(payload.get("task_id")),
            content=str(payload.get("content") or ""),
            author_type=str(payload.get("author_type") or "user"),
            content_type=str(payload.get("content_type") or "text"),
            importance_score=float(payload.get("importance_score", 0.5) or 0.5),
            level=int(payload.get("level", 1) or 1),
            media_path=self._non_empty_text(payload.get("media_path")),
        )

    async def _load_context_texts(self, event: MemoryEvent, *, exclude_event_ids: list[str] | None = None) -> list[str]:
        if self._l1_store is None:
            return []

        query_args: dict[str, Any] = {"cognition_eligible": True, "limit": max(4, len(exclude_event_ids or []) + 4)}
        if event.session_id:
            query_args["session_id"] = event.session_id
        elif event.user_id:
            query_args["user_id"] = event.user_id
        else:
            return []

        rows = await self._l1_store.query_events(**query_args)
        excluded = set(exclude_event_ids or [])
        excluded.add(event.event_id)
        context_rows = [row for row in rows if row["event_id"] not in excluded]
        context_texts = [str(row["content"]) for row in reversed(context_rows) if str(row["content"]).strip()]
        return context_texts[:3]

    async def _load_context_messages(
        self,
        event: MemoryEvent,
        *,
        exclude_event_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Load recent context messages with author_type role annotation."""
        if self._l1_store is None:
            return []

        query_args: dict[str, Any] = {"cognition_eligible": True, "limit": max(4, len(exclude_event_ids or []) + 4)}
        if event.session_id:
            query_args["session_id"] = event.session_id
        elif event.user_id:
            query_args["user_id"] = event.user_id
        else:
            return []

        rows = await self._l1_store.query_events(**query_args)
        excluded = set(exclude_event_ids or [])
        excluded.add(event.event_id)
        context_rows = [row for row in rows if row["event_id"] not in excluded]
        messages: list[dict[str, Any]] = []
        for row in reversed(context_rows):
            content = str(row.get("content", "")).strip()
            if not content:
                continue
            role = str(row.get("author_type", "user")).strip() or "user"
            messages.append({"role": role, "content": content})
        return messages[:3]

    async def _load_existing_graph_context(
        self,
        focal_entities: list[L2FocalEntityRef],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Load existing graph edges and assertions for focal entities."""
        if self._cognition_store is None:
            return [], []

        graph_edges: list[dict[str, Any]] = []
        assertions: list[dict[str, Any]] = []
        seen_triple_ids: set[str] = set()
        seen_assertion_ids: set[str] = set()

        for entity in focal_entities:
            # Load graph edges
            for relations in [
                await self._cognition_store.get_relationships(subject_id=entity.entity_id, limit=30),
                await self._cognition_store.get_relationships(object_id=entity.entity_id, limit=30),
            ]:
                for relation in relations:
                    triple_id = str(relation.get("triple_id", ""))
                    if triple_id in seen_triple_ids:
                        continue
                    seen_triple_ids.add(triple_id)
                    graph_edges.append(relation)

            # Load assertions
            entity_assertions = await self._cognition_store.list_tom_assertions(
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                limit=20,
            )
            for assertion in entity_assertions:
                assertion_id = str(assertion.get("assertion_id", ""))
                if assertion_id in seen_assertion_ids:
                    continue
                seen_assertion_ids.add(assertion_id)
                assertions.append(assertion)

        return graph_edges[:30], assertions[:20]

    async def _load_history_contexts(
        self,
        *,
        anchor_event: MemoryEvent,
        batch_events: list[MemoryEvent],
        exclude_event_ids: list[str] | None = None,
    ) -> list[L2HistoryContext]:
        if self._l1_store is None or self._entity_catalog is None or not anchor_event.user_id:
            return []

        query_text = " ".join(
            text
            for event in batch_events
            if (text := self._non_empty_text(event.content))
        ).strip()
        if not query_text:
            return []

        entity_matches = await self._entity_catalog.resolve_query_entities(
            query_text,
            limit=DEFAULT_L2_HISTORY_ENTITY_MATCH_LIMIT,
        )
        if not entity_matches:
            return []

        seen_event_ids = set(exclude_event_ids or [])
        seen_terms: set[str] = set()
        matches_by_event_id: dict[str, L2HistoryContext] = {}
        for match in entity_matches:
            candidate_terms = [
                self._non_empty_text(match.get("matched_text")),
                self._non_empty_text(match.get("canonical_name")),
            ]
            for term in candidate_terms:
                if term is None:
                    continue
                normalized_term = term.casefold()
                if normalized_term in seen_terms:
                    continue
                seen_terms.add(normalized_term)
                rows = await self._l1_store.search_events(
                    query=term,
                    user_id=anchor_event.user_id,
                    limit=DEFAULT_L2_HISTORY_SEARCH_LIMIT,
                )
                for row in rows:
                    event_id = self._non_empty_text(row.get("event_id"))
                    content = self._non_empty_text(row.get("content"))
                    if not event_id or not content or event_id in seen_event_ids:
                        continue
                    if not bool(row.get("cognition_eligible", True)):
                        continue
                    if anchor_event.session_id and str(row.get("session_id") or "") == anchor_event.session_id:
                        continue
                    history_context = L2HistoryContext(
                        event_id=event_id,
                        session_id=self._non_empty_text(row.get("session_id")),
                        timestamp=float(row.get("timestamp", 0.0) or 0.0),
                        content=content,
                        matched_entity_id=self._non_empty_text(match.get("entity_id")),
                        matched_text=term,
                        canonical_name=self._non_empty_text(match.get("canonical_name")),
                        match_source=self._non_empty_text(match.get("match_source")),
                    )
                    existing_context = matches_by_event_id.get(event_id)
                    if existing_context is None or history_context.timestamp > existing_context.timestamp:
                        matches_by_event_id[event_id] = history_context
                    seen_event_ids.add(event_id)
        ranked_contexts = sorted(
            matches_by_event_id.values(),
            key=lambda item: (float(item.timestamp), str(item.event_id)),
            reverse=True,
        )
        selected_contexts = ranked_contexts[:DEFAULT_L2_HISTORY_CONTEXT_LIMIT]
        return sorted(
            selected_contexts,
            key=lambda item: (float(item.timestamp), str(item.event_id)),
        )

    async def _collect_context_bundle(
        self,
        event: MemoryEvent,
        *,
        context_texts: list[str],
        source_event_ids: list[str] | None = None,
    ) -> ContextBundle:
        recent_entities: list[dict[str, Any]] = []
        if self._entity_catalog is not None:
            recent_entities = await self._entity_catalog.list_mentions(limit=20)
        return collect_context_bundle(
            event=event,
            recent_messages=[{"text": text} for text in context_texts if text],
            recent_entities=recent_entities,
            source_event_ids=list(source_event_ids or []),
        )

    def _merge_resolved_context_refs(
        self,
        *,
        direct_refs: list[Any],
        llm_refs: list[ResolvedContextRef],
        context_bundle: ContextBundle,
    ) -> list[ResolvedContextRef]:
        allowed_refs = {
            item.context_id: item.kind
            for item in context_bundle.live_context_entities
            if item.expires_at is None or item.expires_at > time.time()
        }
        merged: dict[str, ResolvedContextRef] = {}
        for ref in direct_refs:
            if isinstance(ref, ResolvedContextRef):
                merged[ref.surface] = ref
                continue
            payload = ref.to_dict() if hasattr(ref, "to_dict") else dict(ref)
            surface = self._non_empty_text(payload.get("surface"))
            if not surface:
                continue
            merged[surface] = ResolvedContextRef(
                surface=surface,
                reference_type=self._non_empty_text(payload.get("reference_type")) or "unresolved",
                resolved_ref=self._non_empty_text(payload.get("resolved_ref")) or "",
                resolved_kind=self._non_empty_text(payload.get("resolved_kind")) or "",
                confidence=float(payload.get("confidence", 0.0) or 0.0),
                evidence_text=self._non_empty_text(payload.get("evidence_text")) or "",
            )
        for ref in llm_refs:
            if not isinstance(ref, ResolvedContextRef) or not ref.surface:
                continue
            if ref.reference_type == "context_entity":
                if not ref.resolved_ref or ref.resolved_ref not in allowed_refs:
                    continue
            merged[ref.surface] = ref
        return list(merged.values())

    def _increment_bucket(self, bucket: dict[str, int], key: str | None) -> None:
        if not key:
            return
        bucket[key] = int(bucket.get(key, 0)) + 1

    def _normalize_entity_type(self, raw_value: Any) -> Optional[str]:
        text = self._non_empty_text(raw_value)
        if text is None:
            return None
        return coerce_unknown_entity_type(text)

    def _normalize_predicate(self, raw_value: Any) -> Optional[str]:
        text = self._non_empty_text(raw_value)
        return text.upper() if text else None

    def _normalize_structured_graph_hint_origin_mode(self, raw_value: Any) -> str:
        return str(self._non_empty_text(raw_value) or "source_structured").casefold()

    def _normalize_structured_graph_hint_page_kind(self, attributes: dict[str, Any] | None) -> str | None:
        if not isinstance(attributes, dict):
            return None
        return str(self._non_empty_text(attributes.get("page_kind")) or "").casefold() or None

    def _extract_structured_graph_hint_facets(
        self,
        attributes: dict[str, Any] | None,
    ) -> list[tuple[str, str]]:
        if not isinstance(attributes, dict):
            return []

        raw_values: list[str] = []
        direct_value = self._non_empty_text(attributes.get("category"))
        if direct_value:
            raw_values.append(direct_value)
        raw_categories = attributes.get("categories")
        if isinstance(raw_categories, list):
            raw_values.extend(str(item).strip() for item in raw_categories if str(item).strip())

        facets: list[tuple[str, str]] = []
        seen: set[str] = set()
        for raw_value in raw_values:
            normalized = str(raw_value).strip().casefold()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            facets.append(("category", normalized))
        return facets

    def _build_concept_node(self, *, entity_type: str, normalized_surface: str) -> Optional[str]:
        surface = self._non_empty_text(normalized_surface)
        if not surface:
            return None
        slug = self._slugify(surface)
        return f"{entity_type}:{slug}"

    def _looks_like_interrogative_preference_query(self, text: str | None) -> bool:
        normalized = str(text or "").strip().casefold()
        if not normalized:
            return False
        if any(marker in normalized for marker in ("?", "？", "什么", "哪种", "哪类", "是不是", "吗", "么")):
            return True
        if any(marker in normalized for marker in ("你觉得", "你记得", "你知道", "guess", "do i ", "what ", "which ")):
            return True
        return False

    def _is_generic_preference_object_id(self, value: str | None) -> bool:
        normalized = str(value or "").strip().casefold()
        if not normalized:
            return False
        _, _, suffix = normalized.partition(":")
        candidate = suffix or normalized
        return candidate in _GENERIC_PREFERENCE_OBJECT_SUFFIXES

    def _is_self_like_preference_object(self, *, subject_id: str, object_id: str, object_type: str) -> bool:
        if object_id == subject_id:
            return True
        if object_type != "person":
            return False
        subject_prefix, _, subject_suffix = subject_id.partition(":")
        object_prefix, _, object_suffix = object_id.partition(":")
        if subject_prefix != "user" or object_prefix != "person" or not subject_suffix or not object_suffix:
            return False
        return self._slugify(subject_suffix) == object_suffix

    def _build_canonical_entity_id(self, *, entity_type: str, canonical_name: str) -> str:
        slug = self._slugify(canonical_name)
        return f"{entity_type}:{slug}"

    def _slugify(self, value: str) -> str:
        normalized = value.strip().casefold()
        slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
        if slug:
            return slug
        return uuid.uuid5(uuid.NAMESPACE_URL, normalized).hex[:12]

    def _non_empty_text(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _entity_type_from_id(self, entity_id: str) -> str:
        prefix, _, _ = entity_id.partition(":")
        return prefix or "entity"

__all__ = ["L2Pipeline", "L2PipelineStats"]
