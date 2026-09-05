"""Durable projection and follow-up queue helpers for the L2 pipeline."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import Any, Protocol, cast

from ....core.logger import get_logger
from ...event_contracts import MemoryEvent
from ..batching_policy import (
    DEFAULT_L2_MAX_ESTIMATED_TOKENS_PER_BATCH,
    DEFAULT_L2_MAX_EVENTS_PER_BATCH,
    BatchingPolicy,
    BucketState,
    decide_flush,
)
from ..models import L2BatchJob, L2PendingBatchBucket
from ..store import L2CognitionStore
from .projection import L2PipelineProjectionMixin

logger = get_logger(__name__)

DEFAULT_L2_FLUSH_POLL_INTERVAL_SECONDS = 0.2


class _L2PipelineQueueHostProtocol(Protocol):
    _cognition_store: L2CognitionStore | None
    _extract_queue: asyncio.Queue[L2BatchJob | None]
    _reconcile_queue: asyncio.Queue[list[str] | None]
    _snapshot_queue: asyncio.Queue[list[str] | None]
    _session_touched_entities: dict[str, set[str]]
    _batch_flush_interval_seconds: int
    _projection_claim_limit: int
    _stats: Any

    def _increment_bucket(self, bucket: dict[str, int], key: str | None) -> None: ...

    def _memory_operation_guard(self) -> Any: ...


class L2PipelineQueueMixin(L2PipelineProjectionMixin):
    """Own durable projection claiming and process-local worker queues."""

    async def enqueue_entities(self, entity_ids: list[str]) -> bool:
        host = self._queue_host()
        normalized = sorted(
            {entity_id.strip() for entity_id in entity_ids if entity_id and entity_id.strip()}
        )
        if not normalized or host._cognition_store is None:
            return False
        await host._reconcile_queue.put(normalized)
        host._stats.reconcile_enqueued += 1
        return True

    async def enqueue_snapshot_refresh(self, entity_ids: list[str]) -> bool:
        host = self._queue_host()
        normalized = sorted(
            {entity_id.strip() for entity_id in entity_ids if entity_id and entity_id.strip()}
        )
        if not normalized or host._cognition_store is None:
            return False
        await host._snapshot_queue.put(normalized)
        host._stats.snapshot_enqueued += 1
        return True

    async def flush_session(self, session_id: str) -> list[str]:
        """Enqueue reconciliation for entities touched during a completed session."""
        host = self._queue_host()
        if not session_id or host._cognition_store is None:
            return []

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

    async def flush_pending_projection_jobs(self) -> int:
        """Claim one bounded set of pending durable projection jobs."""
        host = self._queue_host()
        if host._cognition_store is None:
            return 0
        batch_count = await self._claim_pending_projection_jobs(
            limit=host._projection_claim_limit,
            force=True,
        )
        if batch_count:
            logger.info(
                "L2 manual durable projection flush enqueued",
                batch_count=batch_count,
            )
        return int(batch_count)

    def _accumulate_session_entities(
        self,
        session_id: str | None,
        entity_ids: list[str],
    ) -> None:
        if not session_id or not entity_ids:
            return
        host = self._queue_host()
        bucket = host._session_touched_entities.get(session_id)
        if bucket is None:
            bucket = set()
            host._session_touched_entities[session_id] = bucket
        bucket.update(entity_ids)

    def get_statistics(self) -> dict[str, Any]:
        return asdict(self._queue_host()._stats)

    async def _run_flush_worker(self) -> None:
        host = self._queue_host()
        poll_interval = DEFAULT_L2_FLUSH_POLL_INTERVAL_SECONDS
        while host._stats.is_running:
            try:
                await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                break
            async with host._memory_operation_guard():
                await self._claim_pending_projection_jobs()

    async def _enqueue_extract_job(self, job: L2BatchJob) -> None:
        host = self._queue_host()
        if not job.projection_leases:
            raise ValueError("L2 extract jobs require durable projection leases")
        await host._extract_queue.put(job)
        host._stats.extract_enqueued += 1

    def _record_batch_flush(self, job: L2BatchJob, *, flush_reason: str) -> None:
        host = self._queue_host()
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
        host = self._queue_host()
        policy = BatchingPolicy(
            max_events=bucket.max_events or DEFAULT_L2_MAX_EVENTS_PER_BATCH,
            max_estimated_tokens=(
                bucket.max_estimated_tokens or DEFAULT_L2_MAX_ESTIMATED_TOKENS_PER_BATCH
            ),
            max_wait_seconds=float(max(0, host._batch_flush_interval_seconds)),
        )
        state = BucketState(
            event_count=len(bucket.events),
            estimated_tokens=bucket.estimated_tokens,
            oldest_age_seconds=time.time() - bucket.created_at,
        )
        reason = decide_flush(
            state,
            policy,
            batching_enabled=host._batch_flush_interval_seconds > 0,
        )
        return reason.value if reason is not None else None

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

    def _queue_host(self) -> _L2PipelineQueueHostProtocol:
        return self  # type: ignore[return-value]


__all__ = [
    "DEFAULT_L2_FLUSH_POLL_INTERVAL_SECONDS",
    "L2PipelineQueueMixin",
]
