"""Staging and queue helpers for the L2 cognition pipeline."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import Any, Protocol, cast

from ...core.logger import get_logger
from ..event_contracts import MemoryEvent
from ..l1.event_store import L1EventStore
from .models import (
    L2BatchJob,
    L2PendingBatchBucket,
    build_l2_batch_bucket_key,
)
from .store import L2CognitionStore

logger = get_logger(__name__)

DEFAULT_L2_FLUSH_POLL_INTERVAL_SECONDS = 0.2
DEFAULT_L2_MAX_EVENTS_PER_BATCH = 12
DEFAULT_L2_MAX_ESTIMATED_TOKENS_PER_BATCH = 2400


class _L2PipelineStagingHostProtocol(Protocol):
    _cognition_store: L2CognitionStore | None
    _l1_store: L1EventStore | None
    _extract_queue: asyncio.Queue[L2BatchJob | None]
    _reconcile_queue: asyncio.Queue[list[str] | None]
    _snapshot_queue: asyncio.Queue[list[str] | None]
    _staging_buckets: dict[str, L2PendingBatchBucket]
    _staging_lock: asyncio.Lock
    _session_touched_entities: dict[str, set[str]]
    _batch_flush_interval_seconds: int
    _projection_consumer_name: str
    _projection_claim_limit: int
    _projection_stale_queued_timeout_seconds: float
    _projection_stale_running_timeout_seconds: float
    _stats: Any

    def _increment_bucket(self, bucket: dict[str, int], key: str | None) -> None: ...


class L2PipelineStagingMixin:
    """Own event staging, projection claiming, and queue enqueue helpers."""

    async def enqueue_event(self, event: MemoryEvent) -> bool:
        host = self._staging_host()
        if host._cognition_store is None or not event.cognition_eligible:
            host._stats.extract_skipped += 1
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
        async with host._staging_lock:
            bucket = host._staging_buckets.get(bucket_key)
            if bucket is None:
                bucket = L2PendingBatchBucket.for_owner(
                    session_id=event.session_id,
                    user_id=event.user_id,
                    owner_key=str(owner_key) if owner_key is not None else None,
                    max_events=max_events,
                    max_estimated_tokens=max_estimated_tokens,
                )
                host._staging_buckets[bucket_key] = bucket
            bucket.add_event(
                self._serialize_event_for_batch(event),
                estimated_tokens=self._estimate_event_tokens(event.content),
                max_events=max_events,
                max_estimated_tokens=max_estimated_tokens,
            )
            self._refresh_staging_stats_locked()
            flush_reason = self._flush_reason_for_bucket(bucket)
            if flush_reason is not None:
                job_to_flush = self._build_and_remove_bucket_job_locked(
                    bucket_key=bucket_key,
                    flush_reason=flush_reason,
                )

        if job_to_flush is not None:
            await self._enqueue_extract_job(job_to_flush)
        return True

    async def enqueue_entities(self, entity_ids: list[str]) -> bool:
        host = self._staging_host()
        normalized = sorted(
            {entity_id.strip() for entity_id in entity_ids if entity_id and entity_id.strip()}
        )
        if not normalized or host._cognition_store is None:
            return False
        await host._reconcile_queue.put(normalized)
        host._stats.reconcile_enqueued += 1
        return True

    async def enqueue_snapshot_refresh(self, entity_ids: list[str]) -> bool:
        host = self._staging_host()
        normalized = sorted(
            {entity_id.strip() for entity_id in entity_ids if entity_id and entity_id.strip()}
        )
        if not normalized or host._cognition_store is None:
            return False
        await host._snapshot_queue.put(normalized)
        host._stats.snapshot_enqueued += 1
        return True

    async def flush_session(self, session_id: str) -> list[str]:
        """Flush staged session events and enqueue session-end reconciliation."""
        host = self._staging_host()
        if not session_id or host._cognition_store is None:
            return []

        bucket_key = build_l2_batch_bucket_key(session_id=session_id, user_id=None)
        job: L2BatchJob | None = None
        if bucket_key is not None:
            async with host._staging_lock:
                job = self._build_and_remove_bucket_job_locked(
                    bucket_key=bucket_key,
                    flush_reason="session_end",
                )
        if job is not None:
            await self._enqueue_extract_job(job)

        accumulated = sorted(host._session_touched_entities.pop(session_id, set()))
        if accumulated:
            logger.info(
                "L2 session-end review enqueued",
                session_id=session_id,
                entity_count=len(accumulated),
            )
            expired_count = await host._cognition_store.expire_session_decay_assertions(
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
        host = self._staging_host()
        if host._cognition_store is None:
            return 0

        jobs: list[L2BatchJob] = []
        async with host._staging_lock:
            for bucket_key in list(host._staging_buckets.keys()):
                job = self._build_and_remove_bucket_job_locked(
                    bucket_key=bucket_key,
                    flush_reason="manual_flush",
                )
                if job is not None:
                    jobs.append(job)

        for job in jobs:
            await self._enqueue_extract_job(job)

        projection_batch_count = await self._claim_pending_projection_jobs(
            limit=host._projection_claim_limit,
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
        self,
        session_id: str | None,
        entity_ids: list[str],
    ) -> None:
        if not session_id or not entity_ids:
            return
        host = self._staging_host()
        bucket = host._session_touched_entities.get(session_id)
        if bucket is None:
            bucket = set()
            host._session_touched_entities[session_id] = bucket
        bucket.update(entity_ids)

    def get_statistics(self) -> dict[str, int | bool]:
        return cast(dict[str, int | bool], asdict(self._staging_host()._stats))

    async def _run_flush_worker(self) -> None:
        host = self._staging_host()
        poll_interval = DEFAULT_L2_FLUSH_POLL_INTERVAL_SECONDS
        while host._stats.is_running:
            try:
                await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                break
            await self._claim_pending_projection_jobs()
            await self._flush_ready_buckets()

    async def _claim_pending_projection_jobs(
        self,
        *,
        limit: int | None = None,
        force: bool = False,
    ) -> int:
        host = self._staging_host()
        if host._cognition_store is None or host._l1_store is None:
            return 0

        await host._cognition_store.requeue_stale_projection_jobs(
            queued_timeout_seconds=host._projection_stale_queued_timeout_seconds,
            running_timeout_seconds=host._projection_stale_running_timeout_seconds,
        )
        claim_limit = max(1, int(limit or host._projection_claim_limit))
        if force:
            claimed_rows = await host._cognition_store.claim_projection_jobs(
                consumer_name=host._projection_consumer_name,
                limit=claim_limit,
            )
        else:
            claimed_rows = await host._cognition_store.claim_ready_projection_jobs(
                consumer_name=host._projection_consumer_name,
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
            await host._cognition_store.fail_projection_jobs(
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
        host = self._staging_host()
        jobs: list[L2BatchJob] = []
        async with host._staging_lock:
            for bucket_key, bucket in list(host._staging_buckets.items()):
                if bucket.is_flushing or not bucket.events:
                    continue
                flush_reason = self._flush_reason_for_bucket(bucket)
                if flush_reason not in {None, "interval_elapsed"}:
                    continue
                if flush_reason == "interval_elapsed":
                    job = self._build_and_remove_bucket_job_locked(
                        bucket_key=bucket_key,
                        flush_reason=flush_reason,
                    )
                    if job is not None:
                        jobs.append(job)
        for job in jobs:
            await self._enqueue_extract_job(job)

    async def _flush_all_buckets(self, *, flush_reason: str) -> None:
        host = self._staging_host()
        jobs: list[L2BatchJob] = []
        async with host._staging_lock:
            for bucket_key in list(host._staging_buckets.keys()):
                job = self._build_and_remove_bucket_job_locked(
                    bucket_key=bucket_key,
                    flush_reason=flush_reason,
                )
                if job is not None:
                    jobs.append(job)
        for job in jobs:
            await self._enqueue_extract_job(job)

    async def _enqueue_extract_job(self, job: L2BatchJob) -> None:
        host = self._staging_host()
        await host._extract_queue.put(job)
        host._stats.extract_enqueued += 1

    async def _build_extract_jobs_from_projection_rows(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[list[L2BatchJob], list[str]]:
        host = self._staging_host()
        jobs: list[L2BatchJob] = []
        missing_event_ids: list[str] = []
        buckets: dict[str, L2PendingBatchBucket] = {}

        for row in rows:
            event_id = str(row.get("event_id", "")).strip()
            if not event_id:
                continue
            event = (
                await host._l1_store.get_memory_event(event_id)
                if host._l1_store is not None
                else None
            )
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

    def _build_and_remove_bucket_job_locked(
        self,
        *,
        bucket_key: str,
        flush_reason: str,
    ) -> L2BatchJob | None:
        host = self._staging_host()
        bucket = host._staging_buckets.pop(bucket_key, None)
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
        host = self._staging_host()
        host._stats.batch_flush_count += 1
        host._increment_bucket(host._stats.batch_flush_by_reason, flush_reason)
        previous_flushes = host._stats.batch_flush_count - 1
        host._stats.avg_batch_event_count = self._rolling_average(
            current_average=host._stats.avg_batch_event_count,
            previous_count=previous_flushes,
            new_value=float(len(job.events)),
        )
        host._stats.avg_batch_estimated_tokens = self._rolling_average(
            current_average=host._stats.avg_batch_estimated_tokens,
            previous_count=previous_flushes,
            new_value=float(job.estimated_tokens),
        )

    def _flush_reason_for_bucket(self, bucket: L2PendingBatchBucket) -> str | None:
        host = self._staging_host()
        max_events = bucket.max_events or DEFAULT_L2_MAX_EVENTS_PER_BATCH
        max_estimated_tokens = (
            bucket.max_estimated_tokens or DEFAULT_L2_MAX_ESTIMATED_TOKENS_PER_BATCH
        )
        if len(bucket.events) >= max_events:
            return "max_events"
        if bucket.estimated_tokens >= max_estimated_tokens:
            return "token_cap"
        if not bucket.events:
            return None
        if host._batch_flush_interval_seconds <= 0:
            return "interval_elapsed"
        oldest_age_seconds = max(0.0, time.time() - bucket.created_at)
        if oldest_age_seconds >= float(host._batch_flush_interval_seconds):
            return "interval_elapsed"
        return None

    def _refresh_staging_stats_locked(self) -> None:
        host = self._staging_host()
        host._stats.active_bucket_count = len(host._staging_buckets)
        host._stats.pending_staged_event_count = sum(
            len(bucket.events) for bucket in host._staging_buckets.values()
        )

    def _serialize_event_for_batch(self, event: MemoryEvent) -> dict[str, Any]:
        payload = cast(dict[str, Any], event.to_dict())
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
            max(1, int(max_estimated_tokens)) if max_estimated_tokens is not None else None
        )
        return (resolved_max_events, resolved_max_tokens)

    def _rolling_average(
        self,
        *,
        current_average: float,
        previous_count: int,
        new_value: float,
    ) -> float:
        if previous_count <= 0:
            return new_value
        return ((current_average * previous_count) + new_value) / float(previous_count + 1)

    def _staging_host(self) -> _L2PipelineStagingHostProtocol:
        return self  # type: ignore[return-value]
