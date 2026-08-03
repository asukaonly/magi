"""Durable projection claim helpers for the L2 cognition pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ....core.logger import get_logger
from ...event_contracts import MemoryEvent
from ...l1.event_store import L1EventStore
from ..models import (
    L2BatchJob,
    L2PendingBatchBucket,
    L2ProjectionLease,
    build_l2_batch_bucket_key,
)
from ..store import L2CognitionStore

logger = get_logger(__name__)


@dataclass
class _ProjectionBatchBuildState:
    jobs: list[L2BatchJob] = field(default_factory=list)
    missing_leases: list[L2ProjectionLease] = field(default_factory=list)
    buckets: dict[str, L2PendingBatchBucket] = field(default_factory=dict)


class _L2PipelineProjectionHostProtocol(Protocol):
    _cognition_store: L2CognitionStore | None
    _l1_store: L1EventStore | None
    _projection_consumer_name: str
    _projection_claim_limit: int
    _projection_stale_queued_timeout_seconds: float
    _projection_stale_running_timeout_seconds: float

    async def _enqueue_extract_job(self, job: L2BatchJob) -> None: ...

    async def _drain_event_entity_link_outbox(self) -> int: ...

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
        await host._drain_event_entity_link_outbox()
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
        jobs, missing_leases = await self._build_extract_jobs_from_projection_rows(claimed_rows)
        if missing_leases:
            await host._cognition_store.fail_projection_jobs(
                missing_leases,
                error_text="l1_event_not_found",
                requeue=False,
            )
            await host._drain_event_entity_link_outbox()
            logger.warning(
                "L2 projection jobs referenced missing L1 events",
                event_ids=[lease.event_id for lease in missing_leases],
            )

        for job in jobs:
            await host._enqueue_extract_job(job)
        return len(jobs)

    async def _build_extract_jobs_from_projection_rows(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[list[L2BatchJob], list[L2ProjectionLease]]:
        host = self._projection_host()
        state = _ProjectionBatchBuildState()

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
                state.missing_leases.append(_projection_lease(row))
                continue
            self._add_projection_event_to_batch_state(state, row=row, event=event)

        self._flush_remaining_projection_buckets(state)
        return state.jobs, state.missing_leases

    def _add_projection_event_to_batch_state(
        self,
        state: _ProjectionBatchBuildState,
        *,
        row: dict[str, Any],
        event: MemoryEvent,
    ) -> None:
        host = self._projection_host()
        max_events, max_estimated_tokens = host._resolve_batch_limits(event)
        normalized_owner_key = _projection_owner_key(row, event)
        bucket_key = build_l2_batch_bucket_key(
            session_id=event.session_id,
            user_id=event.user_id,
            owner_key=normalized_owner_key,
        )
        if bucket_key is None:
            state.jobs.append(self._build_direct_projection_job(event, row=row))
            return

        bucket = state.buckets.get(bucket_key)
        if bucket is None:
            bucket = L2PendingBatchBucket.for_owner(
                session_id=event.session_id,
                user_id=event.user_id,
                owner_key=normalized_owner_key,
                max_events=max_events,
                max_estimated_tokens=max_estimated_tokens,
            )
            state.buckets[bucket_key] = bucket
        bucket.add_event(
            host._serialize_event_for_batch(event),
            estimated_tokens=host._estimate_event_tokens(event.content),
            max_events=max_events,
            max_estimated_tokens=max_estimated_tokens,
            projection_lease=_projection_lease(row),
        )
        flush_reason = host._flush_reason_for_bucket(bucket)
        if flush_reason is None:
            return
        state.jobs.append(self._build_projection_bucket_job(bucket, flush_reason=flush_reason))
        state.buckets.pop(bucket_key, None)

    def _build_direct_projection_job(
        self,
        event: MemoryEvent,
        *,
        row: dict[str, Any],
    ) -> L2BatchJob:
        host = self._projection_host()
        job = L2BatchJob(
            job_id=f"projection:{event.event_id}",
            bucket_key=f"event:{event.event_id}",
            events=[host._serialize_event_for_batch(event)],
            flush_reason="projection_direct",
            estimated_tokens=host._estimate_event_tokens(event.content),
            session_id=event.session_id,
            user_id=event.user_id,
            projection_leases=[_projection_lease(row)],
        )
        host._record_batch_flush(job, flush_reason=job.flush_reason)
        return job

    def _flush_remaining_projection_buckets(self, state: _ProjectionBatchBuildState) -> None:
        for bucket in state.buckets.values():
            state.jobs.append(
                self._build_projection_bucket_job(bucket, flush_reason="projection_ready")
            )
        state.buckets.clear()

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


def _projection_owner_key(row: dict[str, Any], event: MemoryEvent) -> str | None:
    owner_key = row.get("effective_batch_owner")
    if owner_key is None and isinstance(event.metadata_json, dict):
        owner_key = event.metadata_json.get("l2_batch_owner")
    if owner_key is None:
        owner_key = row.get("batch_owner")
    return str(owner_key) if owner_key is not None else None


def _projection_lease(row: dict[str, Any]) -> L2ProjectionLease:
    return L2ProjectionLease(
        event_id=str(row.get("event_id") or ""),
        lease_token=str(row.get("lease_token") or ""),
        attempt_count=int(row.get("attempt_count") or 0),
    )


__all__ = ["L2PipelineProjectionMixin"]
