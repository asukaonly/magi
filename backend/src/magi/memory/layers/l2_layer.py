"""L2 cognition layer adapters: projection-job (in-lock) and pipeline (deferred)."""

from __future__ import annotations

import logging
from typing import Any

from ..event_contracts import MemoryEvent
from ..evidence import (
    classify_event_evidence,
    policy_allows_l2_projection,
    resolve_l2_policy,
)
from ..l2.pipeline.lifecycle import DEFAULT_L2_BATCH_FLUSH_INTERVAL_SECONDS
from ..l2.pipeline.staging import DEFAULT_L2_MAX_EVENTS_PER_BATCH
from ..layer_protocol import FanOutContext, LayerIngestResult, WILDCARD_EVENT_TYPES


def _coerce(metadata: Any, key: str, cast: Any) -> Any:
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    if value is None:
        return None
    return cast(value)


def _default_batch_owner(event: MemoryEvent) -> str | None:
    session_id = (event.session_id or "").strip()
    if session_id:
        return f"chat:{session_id}"
    return None


logger = logging.getLogger(__name__)


class L2ProjectionLayer:
    layer_name = "l2"
    requires_write_lock = True
    accepts_event_types = WILDCARD_EVENT_TYPES

    def __init__(self, store: Any, *, batch_flush_interval_seconds: int | None = None) -> None:
        self._store = store
        self._batch_flush_interval_seconds = (
            int(batch_flush_interval_seconds)
            if batch_flush_interval_seconds is not None
            else None
        )

    def accepts(self, event: MemoryEvent, ctx: FanOutContext) -> bool:
        if self._store is None:
            return False
        if not event.cognition_eligible:
            return False
        if not event.ingest_target.includes_l1:
            return False
        return ctx.markers.get("stored_event_id") is not None

    async def ingest(self, event: MemoryEvent, ctx: FanOutContext) -> LayerIngestResult:
        stored_event_id = ctx.markers.get("stored_event_id")
        policy_markers = self._resolve_policy_markers(event)
        if not policy_markers["l2_policy_allows_projection"]:
            return LayerIngestResult(
                layer_name=self.layer_name,
                ok=True,
                markers={
                    "l2_job_enqueued": False,
                    "l2_job_skipped_by_policy": True,
                    "l2_evidence_class": policy_markers["l2_evidence_class"],
                    "l2_skip_reason": policy_markers["l2_skip_reason"],
                },
            )
        metadata = event.metadata_json
        batch_owner = _coerce(metadata, "l2_batch_owner", str)
        max_events = _coerce(metadata, "l2_batch_max_events", int)
        max_wait_seconds = _coerce(metadata, "l2_batch_max_wait_seconds", float)
        if batch_owner is None and self._batching_enabled():
            batch_owner = _default_batch_owner(event)
            if batch_owner is not None:
                if max_events is None:
                    max_events = DEFAULT_L2_MAX_EVENTS_PER_BATCH
                if max_wait_seconds is None:
                    max_wait_seconds = float(self._effective_max_wait_seconds())
        l2_job_enqueued = await self._store.enqueue_projection_job(
            event_id=stored_event_id,
            source=event.source,
            event_type=event.event_type,
            batch_owner=batch_owner,
            catch_up_owner=_coerce(metadata, "l2_batch_catch_up_owner", str),
            max_events=max_events,
            min_ready_events=_coerce(metadata, "l2_batch_min_ready_events", int),
            max_wait_seconds=max_wait_seconds,
        )
        return LayerIngestResult(
            layer_name=self.layer_name,
            ok=True,
            markers={
                "l2_job_enqueued": bool(l2_job_enqueued),
                "l2_evidence_class": policy_markers["l2_evidence_class"],
            },
        )

    def _resolve_policy_markers(self, event: MemoryEvent) -> dict[str, Any]:
        try:
            classification = classify_event_evidence(event)
        except Exception as exc:
            logger.warning(
                "L2 projection evidence classification failed | event_id=%s error=%s",
                event.event_id,
                exc,
            )
            return {
                "l2_policy_allows_projection": False,
                "l2_evidence_class": "unknown",
                "l2_skip_reason": "classification_error",
            }
        try:
            policy = resolve_l2_policy(classification)
        except Exception as exc:
            logger.warning(
                "L2 projection evidence policy failed | event_id=%s evidence_class=%s error=%s",
                event.event_id,
                classification.evidence_class,
                exc,
            )
            return {
                "l2_policy_allows_projection": False,
                "l2_evidence_class": classification.evidence_class,
                "l2_skip_reason": "policy_error",
            }
        allowed = policy_allows_l2_projection(policy)
        return {
            "l2_policy_allows_projection": allowed,
            "l2_evidence_class": classification.evidence_class,
            "l2_skip_reason": None if allowed else policy.skip_reason or "policy_blocked",
        }

    def _batching_enabled(self) -> bool:
        return (
            self._batch_flush_interval_seconds is None
            or self._batch_flush_interval_seconds > 0
        )

    def _effective_max_wait_seconds(self) -> int:
        if self._batch_flush_interval_seconds is None:
            return DEFAULT_L2_BATCH_FLUSH_INTERVAL_SECONDS
        return self._batch_flush_interval_seconds


class L2PipelineLayer:
    layer_name = "l2_pipeline"
    requires_write_lock = False
    accepts_event_types = WILDCARD_EVENT_TYPES

    def __init__(self, store: Any, pipeline: Any) -> None:
        self._store = store
        self._pipeline = pipeline

    def accepts(self, event: MemoryEvent, ctx: FanOutContext) -> bool:
        if self._pipeline is None:
            return False
        if not event.cognition_eligible:
            return False
        return not event.ingest_target.includes_l1 or self._store is None

    async def ingest(self, event: MemoryEvent, ctx: FanOutContext) -> LayerIngestResult:
        stored_event_id = ctx.markers.get("stored_event_id")
        if stored_event_id is not None and stored_event_id != event.event_id:
            event.event_id = stored_event_id
        await self._pipeline.enqueue_event(event)
        return LayerIngestResult(
            layer_name=self.layer_name,
            ok=True,
            markers={"l2_pipeline_enqueued": True},
        )


__all__ = ["L2ProjectionLayer", "L2PipelineLayer"]
