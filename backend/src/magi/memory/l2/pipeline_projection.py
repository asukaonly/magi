"""Durable projection claim helpers for the L2 cognition pipeline."""

from __future__ import annotations

from typing import Any, Protocol

from ...core.logger import get_logger
from ..event_contracts import MemoryEvent
from ..l1.event_store import L1EventStore
from .models import L2BatchJob, L2PendingBatchBucket, build_l2_batch_bucket_key
from .store import L2CognitionStore

logger = get_logger(__name__)


class _L2PipelineProjectionHostProtocol(Protocol):
    _cognition_store: L2CognitionStore | None
    _l1_store: L1EventStore | None
    _projection_consumer_name: str
    _projection_claim_limit: int
    _projection_stale_queued_timeout_seconds: float
    _projection_stale_running_timeout_seconds: float

    async def _enqueue_extract_job(self, job: L2BatchJob) -> None: ...

    def _resolve_batch_limits(self, event: MemoryEvent) -> tuple[int | None, int | None]: ...

    def _serialize_event_for_batch(self, event: MemoryEvent) -> dict[str, Any]: ...

    def _estimate_event_tokens(self, text: str) -> int: ...

    def _flush_reason_for_bucket(self, bucket: L2PendingBatchBucket) -> str | None: ...

    def _record_batch_flush(self, job: L2BatchJob, *, flush_reason: str) -> None: ...


class L2PipelineProjectionMixin:
    """Own durable projection claiming and projection-row batch construction."""

    async def _claim_pending_projection_jobs(
        self,
        *,
        limit: int | None = None,
        force: bool = False,
    ) -> int:
        host = self._projection_host()
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
            await host._enqueue_extract_job(job)
        return len(jobs)

    async def _build_extract_jobs_from_projection_rows(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[list[L2BatchJob], list[str]]:
        host = self._projection_host()
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

            max_events, max_estimated_tokens = host._resolve_batch_limits(event)
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
                    events=[host._serialize_event_for_batch(event)],
                    flush_reason="projection_direct",
                    estimated_tokens=host._estimate_event_tokens(event.content),
                    session_id=event.session_id,
                    user_id=event.user_id,
                )
                host._record_batch_flush(direct_job, flush_reason=direct_job.flush_reason)
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
                host._serialize_event_for_batch(event),
                estimated_tokens=host._estimate_event_tokens(event.content),
                max_events=max_events,
                max_estimated_tokens=max_estimated_tokens,
            )
            flush_reason = host._flush_reason_for_bucket(bucket)
            if flush_reason is not None:
                jobs.append(self._build_projection_bucket_job(bucket, flush_reason=flush_reason))
                buckets.pop(bucket_key, None)

        for bucket in buckets.values():
            jobs.append(self._build_projection_bucket_job(bucket, flush_reason="projection_ready"))
        return jobs, missing_event_ids

    def _build_projection_bucket_job(
        self,
        bucket: L2PendingBatchBucket,
        *,
        flush_reason: str,
    ) -> L2BatchJob:
        host = self._projection_host()
        job = bucket.build_job(
            flush_reason=flush_reason,
            job_id=f"projection:{bucket.bucket_key}:{int(bucket.newest_event_timestamp * 1000)}",
        )
        host._record_batch_flush(job, flush_reason=flush_reason)
        return job

    def _projection_host(self) -> _L2PipelineProjectionHostProtocol:
        return self  # type: ignore[return-value]


__all__ = ["L2PipelineProjectionMixin"]
