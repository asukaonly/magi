"""Asynchronous queue workers for L2 cognition processing."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ...core.logger import get_logger
from ..event_contracts import MemoryEvent
from ..l1.event_store import L1EventStore
from .context_bundle import ContextBundle, ResolvedContextRef
from .context_collector import collect_context_bundle, resolve_direct_context_refs
from .models import (
    ContradictionHint,
    L2AssertionCandidate,
    L2BatchJob,
    L2CandidateSet,
    L2ConflictArbitrationResult,
    L2EntityCandidate,
    L2ExistingRecord,
    L2EntityResolutionMention,
    L2EventWindow,
    L2EventWindowSummary,
    L2FocalEntityRef,
    L2GraphCandidate,
    L2HistoryContext,
    L2Phase1Result,
    L2Phase2ContradictionHint,
    L2Phase2GraphEdge,
    L2Phase2Result,
    L2PendingBatchBucket,
    L2SourceEvent,
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
from .ontology import (
    coerce_unknown_entity_type,
    is_leaf_fact_duplicate,
    validate_assertion_candidate,
    validate_graph_candidate,
)

_PREFERENCE_PREDICATES = {"LIKES", "DISLIKES", "INTERESTED_IN"}
_TOPOLOGY_ONLY_TRAIT_FAMILIES = {"public_sentiment", "group_atmosphere", "relationship_shift"}
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
DEFAULT_L2_PROJECTION_STALE_CLAIM_TIMEOUT_SECONDS = 30.0
DEFAULT_L2_HISTORY_ENTITY_MATCH_LIMIT = 3
DEFAULT_L2_HISTORY_CONTEXT_LIMIT = 3
DEFAULT_L2_HISTORY_SEARCH_LIMIT = 4
DEFAULT_ENABLE_L2_CONFLICT_ARBITRATION = True
DEFAULT_L2_CONFLICT_ARBITRATION_MIN_CONFIDENCE = 0.85
SEVERE_CONTRADICTION_KINDS = {
    "direct_negation",
    "state_reversal",
    "exclusive_role_conflict",
    "preference_reversal",
}


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


class L2Pipeline:
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
    ) -> None:
        if cognition_store is not None and entity_catalog is None:
            raise ValueError("entity_catalog is required when cognition_store is enabled")
        if cognition_store is not None and llm_service is None:
            raise ValueError("llm_service is required when cognition_store is enabled")
        self._cognition_store = cognition_store
        self._l1_store = l1_store
        self._entity_catalog = entity_catalog
        self._llm_service = llm_service
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
        self._session_touched_entities: dict[str, set[str]] = {}
        self._stats = L2PipelineStats()
        self._projection_consumer_name = f"l2-pipeline:{uuid.uuid4().hex[:8]}"
        self._projection_claim_limit = DEFAULT_L2_PROJECTION_CLAIM_LIMIT
        self._projection_stale_claim_timeout_seconds = DEFAULT_L2_PROJECTION_STALE_CLAIM_TIMEOUT_SECONDS

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

        projection_batch_count = await self._claim_pending_projection_jobs(limit=self._projection_claim_limit)
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

    async def _claim_pending_projection_jobs(self, *, limit: int | None = None) -> int:
        if self._cognition_store is None or self._l1_store is None:
            return 0

        await self._cognition_store.requeue_stale_projection_jobs(
            timeout_seconds=self._projection_stale_claim_timeout_seconds,
        )
        claimed_rows = await self._cognition_store.claim_projection_jobs(
            consumer_name=self._projection_consumer_name,
            limit=max(1, int(limit or self._projection_claim_limit)),
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
            owner_key = None
            if isinstance(event.metadata_json, dict):
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
            jobs.append(self._build_projection_bucket_job(bucket, flush_reason="projection_claim"))
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

        # Pre-register structured entity hints from sensor metadata
        await self._register_structured_entity_hints(
            stored_event, existing_entities, batch_event_ids,
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
        )

        # Register Phase 1 entities in the entity catalog
        resolved_mentions: list[ResolvedEntityMention] = []
        if policy.allow_entity_extraction and phase1_result.entities:
            resolved_mentions = await self._resolve_phase1_entities(
                stored_event,
                phase1_result,
                evidence_event_ids=batch_event_ids,
            )

        logger.debug(
            "L2 Phase 1 completed",
            event_id=stored_event.event_id,
            entity_count=len(phase1_result.entities),
            fact_claim_count=len(phase1_result.fact_claims),
            resolved_ref_count=len(phase1_result.resolved_refs),
            resolved_mention_count=len(resolved_mentions),
        )

        # Skip Phase 2 if Phase 1 produced nothing useful
        if not phase1_result.has_content:
            return {
                "relation_count": 0,
                "assertion_count": 0,
                "touched_entity_ids": [],
                "snapshot_refresh_entity_ids": [],
                "skipped": False,
                "evidence_class": classification.evidence_class,
                "profile_id": extraction_profile.profile_id,
                "mention_count": len(phase1_result.entities),
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
        graph_candidates, rejected_graph_candidate_count = self._validate_phase2_graph_edges(
            event=stored_event,
            profile=extraction_profile,
            policy=policy,
            resolved_mentions=resolved_mentions,
            evidence_event_ids=batch_event_ids,
            phase2_edges=phase2_result.graph_edges,
        )

        assertion_candidates, rejected_assertion_candidate_count = self._validate_phase2_assertions(
            event=stored_event,
            profile=extraction_profile,
            policy=policy,
            graph_candidates=graph_candidates,
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
        assertion_count = 0
        for candidate in graph_candidates:
            await self._cognition_store.upsert_knowledge_edge(**candidate)
            relation_count += 1

        for candidate in assertion_candidates:
            await self._cognition_store.upsert_assertion_candidate(candidate)
            assertion_count += 1

        for hint in contradiction_hints:
            await self._cognition_store.apply_contradiction_hint(hint)

        logger.info(
            "L2 persistence completed",
            event_id=stored_event.event_id,
            profile_id=extraction_profile.profile_id,
            relation_count=relation_count,
            assertion_count=assertion_count,
            contradiction_hint_count=len(contradiction_hints),
            conflict_arbitration_decision=conflict_arbitration.decision if conflict_arbitration is not None else None,
        )

        conflict_arbitration_decision = conflict_arbitration.decision if conflict_arbitration is not None else None
        touched_entity_ids = self._collect_touched_entities(graph_candidates, assertion_candidates)
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

    async def _register_structured_entity_hints(
        self,
        event: MemoryEvent,
        existing_entities: list[dict[str, Any]],
        evidence_event_ids: list[str],
    ) -> None:
        """Pre-register structured entity hints from sensor metadata into the catalog."""
        if self._entity_catalog is None:
            return
        metadata_json = event.metadata_json
        if not isinstance(metadata_json, dict):
            return
        hints = metadata_json.get("structured_entity_hints")
        if not hints or not isinstance(hints, list):
            return

        existing_ids = {str(e.get("entity_id", "")) for e in existing_entities}
        registered_count = 0
        for hint in hints:
            if not isinstance(hint, dict):
                continue
            mention_text = str(hint.get("mention_text", "")).strip()
            entity_type = self._normalize_entity_type(hint.get("entity_type"))
            if not mention_text or not entity_type:
                continue

            canonical_name = str(hint.get("canonical_name_hint") or mention_text).strip()
            resolved_id = hint.get("resolved_entity_id")
            if resolved_id:
                entity_id = str(resolved_id)
            else:
                entity_id = self._build_canonical_entity_id(
                    entity_type=entity_type, canonical_name=canonical_name,
                )

            if entity_id in existing_ids:
                continue

            await self._entity_catalog.upsert_entity(
                entity_id=entity_id,
                canonical_name=canonical_name,
                entity_type=entity_type,
            )
            await self._entity_catalog.add_alias(
                entity_id=entity_id,
                alias_text=canonical_name,
                confidence=0.95,
            )
            existing_entities.append({
                "entity_id": entity_id,
                "canonical_name": canonical_name,
                "entity_type": entity_type,
                "aliases": [canonical_name],
            })
            existing_ids.add(entity_id)
            registered_count += 1

        if registered_count:
            logger.info(
                "L2 structured entity hints registered",
                event_id=event.event_id,
                hint_count=len(hints),
                registered_count=registered_count,
            )

    async def _resolve_phase1_entities(
        self,
        event: MemoryEvent,
        phase1_result: L2Phase1Result,
        *,
        evidence_event_ids: list[str],
    ) -> list[ResolvedEntityMention]:
        """Register Phase 1 entities in the entity catalog and return resolved mentions."""
        if self._entity_catalog is None:
            return []

        resolved_mentions: list[ResolvedEntityMention] = []
        for entity in phase1_result.entities:
            if not entity.surface:
                continue
            mention_text = entity.surface
            normalized_surface = entity.normalized_name or mention_text
            entity_type = self._normalize_entity_type(entity.entity_type)
            mention_confidence = entity.confidence

            # If Phase 1 already resolved the entity to an existing ID, use it
            resolved_entity_id: str | None = entity.resolved_id
            resolved_confidence: float | None = entity.confidence if entity.resolved_id else None

            # If not resolved by Phase 1, try catalog alias resolution then LLM resolution
            if not resolved_entity_id:
                resolved_entity_id, resolved_confidence = await self._resolve_entity_id(
                    mention={"mention_text": mention_text, "canonical_name_hint": normalized_surface, "alias_signals": entity.alias_signals},
                    entity_type=entity_type,
                    mention_text=mention_text,
                    mention_confidence=mention_confidence,
                    event=event,
                )

            # Ensure the entity exists in the catalog before recording the mention (FK constraint)
            if resolved_entity_id:
                await self._entity_catalog.upsert_entity(
                    canonical_name=normalized_surface,
                    entity_type=entity_type,
                    entity_id=resolved_entity_id,
                )

            await self._entity_catalog.record_mention(
                mention_text=mention_text,
                normalized_surface=normalized_surface,
                entity_type=entity_type,
                evidence_event_ids=list(evidence_event_ids),
                evidence_text=mention_text,
                resolved_entity_id=resolved_entity_id,
                confidence=resolved_confidence,
            )
            resolved_mentions.append(
                ResolvedEntityMention(
                    mention_text=mention_text,
                    normalized_surface=normalized_surface,
                    entity_type=entity_type,
                    resolved_entity_id=resolved_entity_id,
                    confidence=resolved_confidence,
                )
            )
        return resolved_mentions

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

    def _validate_phase2_graph_edges(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        resolved_mentions: list[ResolvedEntityMention],
        evidence_event_ids: list[str],
        phase2_edges: list[L2Phase2GraphEdge],
    ) -> tuple[list[dict[str, Any]], int]:
        """Validate Phase 2 graph edges against ontology and profile constraints."""
        if not policy.allow_graph_write or not profile.allow_graph or policy.graph_scope != "full":
            return [], 0

        prepared: list[dict[str, Any]] = []
        rejected_count = 0
        for edge in phase2_edges:
            object_type = self._normalize_entity_type(edge.object_type)
            predicate = self._normalize_predicate(edge.predicate)
            if object_type not in profile.allowed_entity_types:
                rejected_count += 1
                continue
            if predicate not in profile.allowed_predicates:
                rejected_count += 1
                continue
            is_valid, _ = validate_graph_candidate(
                {"predicate": predicate, "object_type": object_type}
            )
            if not is_valid:
                rejected_count += 1
                continue

            subject_id = self._resolve_phase2_subject_id(event=event, subject_ref=edge.subject_ref)
            if not subject_id:
                rejected_count += 1
                continue
            object_id = self._resolve_phase2_object_id(
                raw_object_ref=edge.object_ref,
                object_type=object_type,
                resolved_mentions=resolved_mentions,
            )
            if not object_id:
                rejected_count += 1
                continue
            if self._should_reject_preference_graph_candidate(
                event=event,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                object_type=object_type,
                raw_object_ref=edge.object_ref,
            ):
                rejected_count += 1
                continue
            prepared.append(
                {
                    "subject_id": subject_id,
                    "subject_type": edge.subject_type or "user",
                    "predicate": predicate,
                    "object_id": object_id,
                    "object_type": object_type,
                    "evidence_event_ids": list(edge.supporting_event_ids or evidence_event_ids),
                    "confidence": edge.confidence,
                    "observed_at": event.timestamp,
                    "source_type": event.source,
                    "extraction_method": "llm_phase2_integration",
                }
            )
        return prepared, rejected_count

    def _validate_phase2_assertions(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        graph_candidates: list[dict[str, Any]],
        default_event_ids: list[str],
        phase2_assertions: list,
    ) -> tuple[list[dict[str, Any]], int]:
        """Validate Phase 2 assertion candidates."""
        if not policy.allow_assertion_write or not profile.allow_assertion:
            return [], 0

        prepared: list[dict[str, Any]] = []
        rejected_count = 0
        duplicate_check_candidates = [
            {"predicate": c["predicate"], "object_ref": c["object_id"]}
            for c in graph_candidates
        ]
        for assertion in phase2_assertions:
            trait_family = str(getattr(assertion, "trait_family", "") or "").casefold()
            if trait_family not in profile.allowed_assertion_families:
                rejected_count += 1
                continue
            assertion_dict = assertion.to_dict() if hasattr(assertion, "to_dict") else dict(assertion)
            is_valid, _ = validate_assertion_candidate(assertion_dict)
            if not is_valid:
                rejected_count += 1
                continue
            if is_leaf_fact_duplicate(duplicate_check_candidates, assertion_dict):
                rejected_count += 1
                continue

            # Build normalized assertion for persistence
            self_entity_id = self._resolve_self_entity_id(event)
            entity_ref = self._non_empty_text(assertion.entity_ref)
            if entity_ref and entity_ref.startswith("user:") and self_entity_id:
                entity_ref = self_entity_id

            trait_value = assertion.trait_value
            if isinstance(trait_value, (dict, list)):
                trait_value = json.dumps(trait_value, ensure_ascii=False, sort_keys=True)
            elif trait_value is None:
                trait_value = ""

            inference_depth = self._non_empty_text(getattr(assertion, "inference_depth", "")) or event.tom_depth.label
            volatility_index = float(getattr(assertion, "volatility_index", 0.5) or 0.5)

            # Derive decay policy from trait family
            temporal_scope, decay_policy, expires_at = self._derive_assertion_decay_from_family(
                event=event,
                trait_family=trait_family,
                trait_name=str(getattr(assertion, "trait_name", "") or ""),
            )

            prepared.append({
                "entity_id": entity_ref or self_entity_id or "",
                "entity_type": str(getattr(assertion, "entity_type", "user") or "user"),
                "trait_family": trait_family,
                "trait_name": str(getattr(assertion, "trait_name", "") or ""),
                "trait_value": str(trait_value),
                "confidence_score": float(getattr(assertion, "confidence", 0.0) or 0.0),
                "evidence_events": list(getattr(assertion, "supporting_event_ids", None) or default_event_ids),
                "volatility_index": volatility_index,
                "source_domain": event.memory_domain.label,
                "inference_depth": inference_depth,
                "validation_state": "tentative",
                "first_inferred_at": event.timestamp,
                "last_validated_at": event.timestamp,
                "target_entity_id": "",
                "target_entity_type": "",
                "target_scope": "global",
                "temporal_scope": temporal_scope,
                "decay_policy": decay_policy,
                "decay_anchor_at": event.timestamp,
                "context_ref_id": "",
                "expires_at": expires_at,
            })
        return prepared, rejected_count

    def _convert_phase2_contradiction_hints(
        self,
        phase2_hints: list[L2Phase2ContradictionHint],
    ) -> list[ContradictionHint]:
        """Convert Phase 2 contradiction hints to the ContradictionHint format."""
        hints: list[ContradictionHint] = []
        for h in phase2_hints:
            if not h.target_record_id or not h.target_record_type or not h.contradiction_kind:
                continue
            hints.append(
                ContradictionHint(
                    target_record_id=h.target_record_id,
                    target_record_type=h.target_record_type,
                    contradiction_kind=h.contradiction_kind,
                    confidence=h.confidence,
                    evidence_text=h.evidence_text,
                    recommended_action=h.recommended_action,
                )
            )
        return hints

    def _resolve_phase2_subject_id(self, *, event: MemoryEvent, subject_ref: str) -> str | None:
        ref = self._non_empty_text(subject_ref)
        if ref:
            if ref.startswith("user:"):
                return self._resolve_self_entity_id(event) or ref
            return ref
        return self._resolve_self_entity_id(event)

    def _resolve_phase2_object_id(
        self,
        *,
        raw_object_ref: Any,
        object_type: str,
        resolved_mentions: list[ResolvedEntityMention],
    ) -> str | None:
        object_ref = self._non_empty_text(raw_object_ref)
        if not object_ref:
            return None
        if ":" in object_ref:
            return object_ref
        object_ref_casefold = object_ref.casefold()
        for mention in resolved_mentions:
            surfaces = {
                mention.mention_text.strip().casefold(),
                mention.normalized_surface.strip().casefold(),
            }
            resolved_entity_id = self._non_empty_text(mention.resolved_entity_id)
            if object_ref_casefold in surfaces and resolved_entity_id:
                return resolved_entity_id
        return self._build_concept_node(entity_type=object_type, normalized_surface=object_ref)

    def _derive_assertion_decay_from_family(
        self,
        *,
        event: MemoryEvent,
        trait_family: str,
        trait_name: str,
    ) -> tuple[str, str, float | None]:
        """Derive decay policy from trait family and name."""
        name_lower = trait_name.casefold()
        if name_lower in {"annoyance", "irritation", "frustration"}:
            return "momentary", "fast_decay", event.timestamp + 2 * 60 * 60
        if trait_family == "mood":
            return "session", "session_decay", event.timestamp + 12 * 60 * 60
        if trait_family == "stress":
            return "daily", "time_window", event.timestamp + 24 * 60 * 60
        if trait_family == "engagement":
            return "session", "session_decay", event.timestamp + 12 * 60 * 60
        if trait_family in {"group_atmosphere", "public_sentiment", "relationship_shift"}:
            return "session", "session_decay", event.timestamp + 6 * 60 * 60
        return "stable", "evidence_only", None

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

    async def _resolve_mentions(
        self,
        event: MemoryEvent,
        mentions: list[dict[str, Any]],
        *,
        evidence_event_ids: list[str] | None = None,
    ) -> list[ResolvedEntityMention]:
        if self._entity_catalog is None:
            return []

        resolved_mentions: list[ResolvedEntityMention] = []
        for mention in mentions:
            if not isinstance(mention, dict):
                continue

            mention_text = str(mention.get("mention_text", "")).strip()
            if not mention_text:
                continue
            normalized_surface = str(mention.get("normalized_surface") or mention_text).strip()
            entity_type = self._normalize_entity_type(mention.get("entity_type"))
            evidence_text = self._non_empty_text(mention.get("evidence_text")) or event.content
            mention_confidence = float(mention.get("confidence", 0.0) or 0.0)

            resolved_entity_id, resolved_confidence = await self._resolve_entity_id(
                mention=mention,
                entity_type=entity_type,
                mention_text=mention_text,
                mention_confidence=mention_confidence,
                event=event,
            )

            await self._entity_catalog.record_mention(
                mention_text=mention_text,
                normalized_surface=normalized_surface,
                entity_type=entity_type,
                evidence_event_ids=list(evidence_event_ids or [event.event_id]),
                evidence_text=evidence_text,
                resolved_entity_id=resolved_entity_id,
                confidence=resolved_confidence,
            )
            resolved_mentions.append(
                ResolvedEntityMention(
                    mention_text=mention_text,
                    normalized_surface=normalized_surface,
                    entity_type=entity_type,
                    resolved_entity_id=resolved_entity_id,
                    confidence=resolved_confidence,
                )
            )
        return resolved_mentions

    async def _resolve_entity_id(
        self,
        *,
        mention: dict[str, Any],
        entity_type: Optional[str],
        mention_text: str,
        mention_confidence: float,
        event: MemoryEvent,
    ) -> tuple[Optional[str], Optional[float]]:
        if self._entity_catalog is None:
            return (None, None)

        alias_resolution = await self._entity_catalog.resolve_alias(
            mention_text,
            entity_type=entity_type,
        )
        if alias_resolution.get("decision") == "match":
            return (str(alias_resolution["entity_id"]), float(alias_resolution["matched_confidence"]))

        if self._llm_service is not None and entity_type:
            candidate_entities = await self._entity_catalog.list_entities_by_type(entity_type=entity_type, limit=20)
            if candidate_entities:
                llm_resolution = await self._llm_service.resolve_entity(
                    mention=L2EntityResolutionMention(
                        mention_text=mention_text,
                        entity_type=entity_type,
                        context_text=event.content,
                    ),
                    candidate_entities=[L2EntityCandidate.from_dict(item) for item in candidate_entities],
                )
                if llm_resolution.decision == "match" and llm_resolution.matched_entity_id:
                    return (
                        str(llm_resolution.matched_entity_id),
                        float(llm_resolution.confidence or mention_confidence),
                    )

        canonical_name = self._non_empty_text(mention.get("canonical_name_hint")) or mention_text
        if not entity_type or mention_confidence < 0.9:
            return (None, mention_confidence if mention_confidence > 0.0 else None)

        entity_id = self._build_canonical_entity_id(entity_type=entity_type, canonical_name=canonical_name)
        await self._entity_catalog.upsert_entity(
            entity_id=entity_id,
            canonical_name=canonical_name,
            entity_type=entity_type,
        )
        await self._entity_catalog.add_alias(
            entity_id=entity_id,
            alias_text=mention_text,
            confidence=min(max(mention_confidence, 0.9), 0.99),
        )
        for alias in mention.get("alias_signals", []):
            alias_text = self._non_empty_text(alias)
            if not alias_text:
                continue
            if not self._is_valid_alias(alias_text, canonical_name, entity_type):
                logger.debug(
                    "L2 alias rejected by validation",
                    alias_text=alias_text,
                    canonical_name=canonical_name,
                    entity_type=entity_type,
                    entity_id=entity_id,
                )
                continue
            await self._entity_catalog.add_alias(
                entity_id=entity_id,
                alias_text=alias_text,
                confidence=min(max(mention_confidence, 0.85), 0.95),
            )
        return (entity_id, mention_confidence)

    _GENERIC_PLATFORM_NAMES: frozenset[str] = frozenset({
        "youtube", "google", "github", "bilibili", "哔哩哔哩", "b站",
        "douyin", "抖音", "tiktok", "tiktok china",
        "zhihu", "知乎", "weibo", "微博",
        "twitter", "x", "reddit", "medium",
        "stackoverflow", "stack overflow", "wikipedia",
        "spotify", "netflix", "twitch",
        "taobao", "淘宝", "jd", "京东",
        "xiaohongshu", "小红书",
        "last.fm", "facebook", "instagram", "linkedin",
        "baidu", "百度", "bing", "yahoo",
    })

    def _is_valid_alias(
        self,
        alias_text: str,
        canonical_name: str,
        entity_type: str,
    ) -> bool:
        """Check whether an alias is semantically valid for the given entity."""
        alias_cf = alias_text.casefold().strip()
        canonical_cf = canonical_name.casefold().strip()
        if alias_cf == canonical_cf:
            return True
        # Reject generic platform names as aliases for non-software entities
        if entity_type != "software" and alias_cf in self._GENERIC_PLATFORM_NAMES:
            return False
        # Reject aliases that are too short relative to a long canonical name
        # (e.g., "抖音" as alias for "坤的真爱粉的抖音直播间")
        if len(canonical_cf) > 8 and len(alias_cf) <= 3:
            return False
        return True

    def _build_focal_entities(
        self,
        event: MemoryEvent,
        resolved_mentions: list[ResolvedEntityMention],
    ) -> list[L2FocalEntityRef]:
        focal_entities: list[L2FocalEntityRef] = []
        self_entity_id = self._resolve_self_entity_id(event)
        if self_entity_id:
            focal_entities.append(L2FocalEntityRef(entity_id=self_entity_id, entity_type="user"))
        seen = {item.entity_id for item in focal_entities}
        for mention in resolved_mentions:
            entity_id = mention.resolved_entity_id
            entity_type = self._normalize_entity_type(mention.entity_type)
            if not entity_id or not entity_type or entity_id in seen:
                continue
            focal_entities.append(L2FocalEntityRef(entity_id=str(entity_id), entity_type=entity_type))
            seen.add(str(entity_id))
        return focal_entities

    def _prepare_unified_graph_candidates(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        resolved_mentions: list[ResolvedEntityMention],
        resolved_context_refs: list[ResolvedContextRef],
        evidence_event_ids: list[str],
        raw_candidates: list[L2GraphCandidate],
    ) -> tuple[list[dict[str, Any]], int]:
        if not policy.allow_graph_write or not profile.allow_graph or policy.graph_scope != "full":
            return [], 0

        prepared: list[dict[str, Any]] = []
        rejected_count = 0
        for raw_candidate in raw_candidates:
            object_type = self._normalize_entity_type(raw_candidate.object_type)
            predicate = self._normalize_predicate(raw_candidate.predicate)
            if object_type not in profile.allowed_entity_types:
                rejected_count += 1
                continue
            if predicate not in profile.allowed_predicates:
                rejected_count += 1
                continue
            is_valid, _ = validate_graph_candidate(
                {
                    "predicate": predicate,
                    "object_type": object_type,
                }
            )
            if not is_valid:
                rejected_count += 1
                continue

            subject_id = self._resolve_subject_id(event=event, raw_candidate=raw_candidate)
            if not subject_id:
                rejected_count += 1
                continue
            object_id = self._resolve_graph_object_id(
                raw_object_ref=raw_candidate.object_ref,
                object_type=object_type,
                resolved_mentions=resolved_mentions,
                resolved_context_refs=resolved_context_refs,
            )
            if not object_id:
                rejected_count += 1
                continue
            if self._should_reject_preference_graph_candidate(
                event=event,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                object_type=object_type,
                raw_object_ref=raw_candidate.object_ref,
            ):
                rejected_count += 1
                continue
            prepared.append(
                {
                    "subject_id": subject_id,
                    "subject_type": raw_candidate.subject_type or "user",
                    "predicate": predicate,
                    "object_id": object_id,
                    "object_type": object_type,
                    "evidence_event_ids": list(evidence_event_ids or [event.event_id]),
                    "confidence": raw_candidate.confidence,
                    "observed_at": event.timestamp,
                    "source_type": event.source,
                    "extraction_method": "llm_two_phase_extraction",
                }
            )
        return prepared, rejected_count

    def _should_reject_preference_graph_candidate(
        self,
        *,
        event: MemoryEvent,
        subject_id: str,
        predicate: str,
        object_id: str,
        object_type: str,
        raw_object_ref: str,
    ) -> bool:
        if predicate not in _PREFERENCE_PREDICATES:
            return False
        if self._looks_like_interrogative_preference_query(event.content):
            return True
        if self._is_generic_preference_object_id(object_id) or self._is_generic_preference_object_id(raw_object_ref):
            return True
        if self._is_self_like_preference_object(subject_id=subject_id, object_id=object_id, object_type=object_type):
            return True
        return False

    def _prepare_unified_assertion_candidates(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        graph_candidates: list[dict[str, Any]],
        resolved_context_refs: list[ResolvedContextRef],
        default_event_ids: list[str],
        raw_candidates: list[L2AssertionCandidate],
    ) -> tuple[list[dict[str, Any]], int]:
        if not policy.allow_assertion_write or not profile.allow_assertion:
            return [], 0

        scoped_assertions = self._apply_assertion_scope(
            raw_candidates=raw_candidates,
            assertion_scope=policy.assertion_scope,
        )
        prepared: list[dict[str, Any]] = []
        rejected_count = max(0, len(raw_candidates) - len(scoped_assertions))
        duplicate_check_candidates = [
            {
                "predicate": candidate["predicate"],
                "object_ref": candidate["object_id"],
            }
            for candidate in graph_candidates
        ]
        for raw_candidate in scoped_assertions:
            if raw_candidate.trait_family.casefold() not in profile.allowed_assertion_families:
                rejected_count += 1
                continue
            is_valid, _ = validate_assertion_candidate(raw_candidate.to_dict())
            if not is_valid:
                rejected_count += 1
                continue
            if is_leaf_fact_duplicate(duplicate_check_candidates, raw_candidate.to_dict()):
                rejected_count += 1
                continue
            prepared.append(
                self._normalize_assertion_candidate(
                    event,
                    raw_candidate,
                    resolved_context_refs,
                    default_event_ids=default_event_ids,
                )
            )
        return prepared, rejected_count

    def _resolve_subject_id(self, *, event: MemoryEvent, raw_candidate: L2GraphCandidate) -> str | None:
        subject_ref = self._non_empty_text(raw_candidate.subject_ref)
        if subject_ref:
            if subject_ref.startswith("user:"):
                return self._resolve_self_entity_id(event) or subject_ref
            return subject_ref
        return self._resolve_self_entity_id(event)

    def _resolve_graph_object_id(
        self,
        *,
        raw_object_ref: Any,
        object_type: str,
        resolved_mentions: list[ResolvedEntityMention],
        resolved_context_refs: list[ResolvedContextRef],
    ) -> str | None:
        object_ref = self._non_empty_text(raw_object_ref)
        if not object_ref:
            return None
        if ":" in object_ref:
            return object_ref
        object_ref_casefold = object_ref.casefold()
        for context_ref in resolved_context_refs:
            if context_ref.surface and context_ref.resolved_ref and context_ref.surface.casefold() == object_ref_casefold:
                return context_ref.resolved_ref
        for mention in resolved_mentions:
            surfaces = {
                mention.mention_text.strip().casefold(),
                mention.normalized_surface.strip().casefold(),
            }
            resolved_entity_id = self._non_empty_text(mention.resolved_entity_id)
            if object_ref_casefold in surfaces and resolved_entity_id:
                return resolved_entity_id
        return self._build_concept_node(entity_type=object_type, normalized_surface=object_ref)

    def _normalize_assertion_candidate(
        self,
        event: MemoryEvent,
        candidate: L2AssertionCandidate,
        resolved_context_refs: list[ResolvedContextRef],
        *,
        default_event_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        trait_value = candidate.trait_value
        if isinstance(trait_value, (dict, list)):
            trait_value = json.dumps(trait_value, ensure_ascii=False, sort_keys=True)
        elif trait_value is None:
            trait_value = ""
        self_entity_id = self._resolve_self_entity_id(event)
        entity_ref = self._non_empty_text(candidate.entity_ref)
        if entity_ref and entity_ref.startswith("user:") and self_entity_id:
            entity_ref = self_entity_id
        target_entity_id, target_entity_type, context_ref_id = self._resolve_assertion_target(
            candidate=candidate,
            resolved_context_refs=resolved_context_refs,
        )
        temporal_scope, decay_policy, expires_at = self._derive_assertion_decay(
            event=event,
            candidate=candidate,
            target_entity_id=target_entity_id,
        )
        return {
            "entity_id": entity_ref or self_entity_id or "",
            "entity_type": candidate.entity_type or "user",
            "trait_family": candidate.trait_family.casefold(),
            "trait_name": candidate.trait_name,
            "trait_value": str(trait_value),
            "confidence_score": candidate.confidence,
            "evidence_events": list(candidate.supporting_event_ids or default_event_ids or [event.event_id]),
            "volatility_index": candidate.volatility_index,
            "source_domain": event.memory_domain.label,
            "inference_depth": candidate.inference_depth or event.tom_depth.label,
            "validation_state": candidate.validation_state or "tentative",
            "first_inferred_at": event.timestamp,
            "last_validated_at": event.timestamp,
            "target_entity_id": target_entity_id or "",
            "target_entity_type": target_entity_type or "",
            "target_scope": "entity_bound" if target_entity_id else "global",
            "temporal_scope": temporal_scope,
            "decay_policy": decay_policy,
            "decay_anchor_at": event.timestamp,
            "context_ref_id": context_ref_id or "",
            "expires_at": expires_at,
        }

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

    def _resolve_assertion_target(
        self,
        *,
        candidate: L2AssertionCandidate,
        resolved_context_refs: list[ResolvedContextRef],
    ) -> tuple[str | None, str | None, str | None]:
        target_ref = self._non_empty_text(candidate.target_ref)
        explicit_target_entity_id = self._non_empty_text(candidate.target_entity_id)
        explicit_target_entity_type = self._normalize_entity_type(candidate.target_entity_type)
        if explicit_target_entity_id:
            return explicit_target_entity_id, explicit_target_entity_type, explicit_target_entity_id
        if not target_ref:
            return None, None, None
        target_ref_casefold = target_ref.casefold()
        for context_ref in resolved_context_refs:
            if context_ref.surface and context_ref.resolved_ref and context_ref.surface.casefold() == target_ref_casefold:
                kind = self._normalize_entity_type(context_ref.resolved_kind) or self._normalize_entity_type(
                    context_ref.resolved_ref.split(":", 1)[0]
                )
                return context_ref.resolved_ref, kind, context_ref.resolved_ref
        return None, None, None

    def _derive_assertion_decay(
        self,
        *,
        event: MemoryEvent,
        candidate: L2AssertionCandidate,
        target_entity_id: str | None,
    ) -> tuple[str, str, float | None]:
        temporal_scope = self._non_empty_text(candidate.temporal_scope)
        decay_policy = self._non_empty_text(candidate.decay_policy)
        expires_at = candidate.expires_at
        if temporal_scope and decay_policy:
            return temporal_scope, decay_policy, float(expires_at) if expires_at is not None else None

        trait_family = candidate.trait_family.casefold()
        trait_name = candidate.trait_name.casefold()
        if target_entity_id and trait_name in {"annoyance", "irritation", "frustration"}:
            return "momentary", "fast_decay", event.timestamp + 2 * 60 * 60
        if trait_family == "mood":
            return "session", "session_decay", event.timestamp + 12 * 60 * 60
        if trait_family == "stress":
            return "daily", "time_window", event.timestamp + 24 * 60 * 60
        if trait_family == "engagement":
            return "session", "session_decay", event.timestamp + 12 * 60 * 60
        if trait_family in {"group_atmosphere", "public_sentiment", "relationship_shift"}:
            return "session", "session_decay", event.timestamp + 6 * 60 * 60
        return "stable", "evidence_only", None

    def _collect_touched_entities(
        self,
        graph_candidates: list[dict[str, Any]],
        assertion_candidates: list[dict[str, Any]],
    ) -> list[str]:
        touched: set[str] = set()
        for candidate in graph_candidates:
            subject_id = candidate.get("subject_id")
            object_id = candidate.get("object_id")
            if subject_id:
                touched.add(str(subject_id))
            if object_id:
                touched.add(str(object_id))
        for candidate in assertion_candidates:
            entity_id = candidate.get("entity_id")
            if entity_id:
                touched.add(str(entity_id))
        return sorted(touched)

    def _resolve_self_entity_id(self, event: MemoryEvent) -> str | None:
        if event.user_id:
            return f"user:{event.user_id}"
        return None

    def _apply_assertion_scope(
        self,
        *,
        raw_candidates: list[L2AssertionCandidate],
        assertion_scope: str,
    ) -> list[L2AssertionCandidate]:
        if assertion_scope == "none":
            return []
        if assertion_scope == "full":
            return list(raw_candidates)
        if assertion_scope == "topology_only":
            return [
                candidate
                for candidate in raw_candidates
                if candidate.trait_family.casefold() in _TOPOLOGY_ONLY_TRAIT_FAMILIES
            ]
        return []

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

    def _severe_contradiction_hints(self, hints: list[ContradictionHint]) -> list[ContradictionHint]:
        severe: list[ContradictionHint] = []
        for hint in hints:
            if hint.contradiction_kind not in SEVERE_CONTRADICTION_KINDS:
                continue
            if float(hint.confidence) < self._conflict_arbitration_min_confidence:
                continue
            severe.append(hint)
        return severe

    async def _arbitrate_conflicting_candidates(
        self,
        *,
        anchor_event: MemoryEvent,
        batch_events: list[MemoryEvent],
        graph_candidates: list[dict[str, Any]],
        assertion_candidates: list[dict[str, Any]],
        contradiction_hints: list[ContradictionHint],
    ) -> L2ConflictArbitrationResult | None:
        if not self._enable_conflict_arbitration or self._llm_service is None or self._cognition_store is None:
            return None

        severe_hints = self._severe_contradiction_hints(contradiction_hints)
        if not severe_hints:
            return None

        existing_records = await self._load_target_records_for_hints(severe_hints)
        if not existing_records:
            return None

        source_events = await self._load_source_events_for_records(
            batch_events=batch_events,
            existing_records=existing_records,
        )
        result = await self._llm_service.arbitrate_conflict(
            new_event_window=L2EventWindow(
                event_ids=[event.event_id for event in batch_events],
                events=[self._serialize_event_for_batch(event) for event in batch_events],
                summary=L2EventWindowSummary(
                    event_count=len(batch_events),
                    session_id=anchor_event.session_id,
                    user_id=anchor_event.user_id,
                ),
            ),
            new_candidates=L2CandidateSet(
                graph_candidates=graph_candidates,
                assertion_candidates=assertion_candidates,
            ),
            contradiction_hints=severe_hints,
            existing_records=existing_records,
            source_events=source_events,
        )
        if not result:
            return None
        self._stats.conflict_arbitration_triggered += 1
        self._stats.severe_contradiction_hint_count += len(severe_hints)
        self._increment_bucket(self._stats.conflict_arbitration_by_decision, result.decision)
        logger.info(
            "L2 conflict arbitration completed",
            event_id=anchor_event.event_id,
            decision=result.decision,
            severe_hint_count=len(severe_hints),
            existing_record_count=len(existing_records),
            source_event_count=len(source_events),
        )
        return result

    def _rewrite_hints_for_evolution(
        self,
        *,
        contradiction_hints: list[ContradictionHint],
        conflict_arbitration: L2ConflictArbitrationResult,
    ) -> list[ContradictionHint]:
        superseded_record_ids = {
            record_id
            for record_id in (
                self._non_empty_text(item)
                for item in conflict_arbitration.superseded_record_ids
            )
            if record_id
        }
        evolved_target_ids = superseded_record_ids or {
            hint.target_record_id for hint in self._severe_contradiction_hints(contradiction_hints) if hint.target_record_id
        }
        rewritten_hints: list[ContradictionHint] = []
        for hint in contradiction_hints:
            next_hint = ContradictionHint(**hint.to_dict())
            if next_hint.target_record_id in evolved_target_ids:
                if next_hint.target_record_type == "knowledge_graph":
                    next_hint.recommended_action = "mark_deprecated"
                elif next_hint.target_record_type == "tom_trait_assertion":
                    next_hint.recommended_action = "mark_conflicted"
            rewritten_hints.append(next_hint)
        return rewritten_hints

    def _rewrite_hints_for_keep_existing(
        self,
        *,
        contradiction_hints: list[ContradictionHint],
        conflict_arbitration: L2ConflictArbitrationResult,
    ) -> list[ContradictionHint]:
        winning_record_ids = {
            record_id
            for record_id in (
                self._non_empty_text(item)
                for item in conflict_arbitration.winning_record_ids
            )
            if record_id
        }
        rewritten_hints: list[ContradictionHint] = []
        for hint in contradiction_hints:
            next_hint = ContradictionHint(**hint.to_dict())
            if not winning_record_ids or next_hint.target_record_id in winning_record_ids:
                next_hint.recommended_action = "revalidate_only"
            rewritten_hints.append(next_hint)
        return rewritten_hints

    async def _load_target_records_for_hints(self, hints: list[ContradictionHint]) -> list[L2ExistingRecord]:
        if self._cognition_store is None:
            return []
        records: list[L2ExistingRecord] = []
        seen: set[str] = set()
        for hint in hints:
            target_record_id = self._non_empty_text(hint.target_record_id)
            target_record_type = self._non_empty_text(hint.target_record_type)
            if not target_record_id or not target_record_type or target_record_id in seen:
                continue
            seen.add(target_record_id)
            if target_record_type == "tom_trait_assertion":
                assertion = await self._cognition_store.get_tom_assertion(assertion_id=target_record_id)
                if assertion is None:
                    continue
                records.append(
                    L2ExistingRecord(
                        record_id=target_record_id,
                        record_type=target_record_type,
                        entity_id=assertion["entity_id"],
                        entity_type=assertion["entity_type"],
                        trait_name=assertion["trait_name"],
                        trait_value=assertion["trait_value"],
                        validation_state=assertion["validation_state"],
                        confidence=assertion["confidence_score"],
                        evidence_event_ids=list(assertion.get("evidence_events", [])),
                    )
                )
                continue
            if target_record_type == "knowledge_graph":
                relation = await self._cognition_store.get_relationship(triple_id=target_record_id)
                if relation is None:
                    continue
                records.append(
                    L2ExistingRecord(
                        record_id=target_record_id,
                        record_type=target_record_type,
                        subject_id=relation["subject_id"],
                        predicate=relation["predicate"],
                        object_id=relation["object_id"],
                        status=relation["status"],
                        confidence=relation["confidence"],
                        evidence_event_ids=list(relation.get("evidence_event_ids", [])),
                    )
                )
        return records

    async def _load_source_events_for_records(
        self,
        *,
        batch_events: list[MemoryEvent],
        existing_records: list[L2ExistingRecord],
    ) -> list[L2SourceEvent]:
        source_events: list[L2SourceEvent] = []
        seen_event_ids: set[str] = set()
        for event in batch_events:
            if event.event_id in seen_event_ids:
                continue
            seen_event_ids.add(event.event_id)
            source_events.append(
                L2SourceEvent(
                    event_id=event.event_id,
                    timestamp=event.timestamp,
                    session_id=event.session_id,
                    user_id=event.user_id,
                    source=event.source,
                    event_type=event.event_type,
                    content=event.content,
                    author_type=event.author_type,
                )
            )
        if self._l1_store is None:
            return source_events
        evidence_event_ids = {
            str(event_id)
            for record in existing_records
            for event_id in record.evidence_event_ids
            if str(event_id).strip()
        }
        for event_id in sorted(evidence_event_ids):
            if event_id in seen_event_ids:
                continue
            row = await self._l1_store.get_event(event_id)
            if row is None:
                continue
            seen_event_ids.add(event_id)
            source_events.append(
                L2SourceEvent(
                    event_id=str(row.get("event_id") or event_id),
                    timestamp=float(row.get("timestamp", 0.0) or 0.0),
                    session_id=self._non_empty_text(row.get("session_id")),
                    user_id=self._non_empty_text(row.get("user_id")),
                    source=str(row.get("source") or "unknown"),
                    event_type=str(row.get("event_type") or ""),
                    content=str(row.get("content") or ""),
                    author_type=str(row.get("author_type") or "user"),
                )
            )
        return source_events

    async def _load_evidence_timestamps(self, entity_id: str) -> dict[str, float]:
        if self._l1_store is None or self._cognition_store is None:
            return {}
        entity_type = self._entity_type_from_id(entity_id)
        assertions = await self._cognition_store.list_tom_assertions(entity_id=entity_id, entity_type=entity_type, limit=500)
        event_ids = sorted({event_id for item in assertions for event_id in item.get("evidence_events", [])})
        timestamps: dict[str, float] = {}
        for event_id in event_ids:
            event = await self._l1_store.get_event(event_id)
            if event is None:
                continue
            timestamps[event_id] = float(event["timestamp"])
        return timestamps

    def _entity_type_from_id(self, entity_id: str) -> str:
        prefix, _, _ = entity_id.partition(":")
        return prefix or "entity"


__all__ = ["L2Pipeline", "L2PipelineStats"]
