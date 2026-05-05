"""L2 cognition layer adapters: projection-job (in-lock) and pipeline (deferred)."""

from __future__ import annotations

from typing import Any

from ..event_contracts import MemoryEvent
from ..layer_protocol import FanOutContext, LayerIngestResult, WILDCARD_EVENT_TYPES


def _coerce(metadata: Any, key: str, cast: Any) -> Any:
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    if value is None:
        return None
    return cast(value)


class L2ProjectionLayer:
    layer_name = "l2"
    requires_write_lock = True
    accepts_event_types = WILDCARD_EVENT_TYPES

    def __init__(self, store: Any) -> None:
        self._store = store

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
        metadata = event.metadata_json
        l2_job_enqueued = await self._store.enqueue_projection_job(
            event_id=stored_event_id,
            source=event.source,
            event_type=event.event_type,
            batch_owner=_coerce(metadata, "l2_batch_owner", str),
            catch_up_owner=_coerce(metadata, "l2_batch_catch_up_owner", str),
            max_events=_coerce(metadata, "l2_batch_max_events", int),
            min_ready_events=_coerce(metadata, "l2_batch_min_ready_events", int),
            max_wait_seconds=_coerce(metadata, "l2_batch_max_wait_seconds", float),
        )
        return LayerIngestResult(
            layer_name=self.layer_name,
            ok=True,
            markers={"l2_job_enqueued": bool(l2_job_enqueued)},
        )


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
