"""Subscribes to SpanCompleted and projects into runtime_trace tables.

Executable spans are written to trace_spans. Control records such as
turn_record update their owning table only, so UI trace trees stay focused on
execution structure instead of persistence bookkeeping.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Optional

from magi.core.operation_barrier import AsyncOperationBarrier
from magi.events.events import Event, EventTypes, published_memory_epoch
from magi.events.domain_payloads import SpanCompleted
from magi.events.payload_helpers import expect_payload, PayloadTypeError
from magi.runtime_trace.writer import RuntimeTraceWriter

logger = logging.getLogger(__name__)


class RuntimeTraceSubscriber:
    """Subscribe to SpanCompleted events; project into runtime_trace tables.

    trace_spans is written for executable events. Sub-tables (trace_tools,
    trace_llm_calls, trace_turns) are written only
    when node_type matches the dispatch table. Handler errors are caught and
    logged so a single bad event cannot kill the subscription.
    """

    def __init__(
        self,
        *,
        event_bus,
        trace_store,
        memory_epoch_getter: Callable[[], int] | None = None,
    ) -> None:
        self._bus = event_bus
        self._store = trace_store
        self._writer = RuntimeTraceWriter(trace_store)
        self._memory_epoch_getter = memory_epoch_getter
        self._sub_id: Optional[str] = None
        self._inflight: set[asyncio.Task] = set()
        self._serialize_lock = asyncio.Lock()
        self._clear_barrier = AsyncOperationBarrier()
        self._clear_generation = 0
        self._clear_request_count = 0
        self._clear_cutoff_started_at_ms = 0

    async def start(self) -> None:
        self._sub_id = await self._bus.subscribe(EventTypes.SPAN_COMPLETED, self._on_span_completed)

    async def stop(self) -> None:
        if self._sub_id is not None:
            try:
                await self._bus.unsubscribe(self._sub_id)
            except Exception:
                logger.exception("unsubscribe failed")
            self._sub_id = None
        await self.drain()

    async def drain(self) -> None:
        if not self._inflight:
            return
        await asyncio.gather(*list(self._inflight), return_exceptions=True)

    @asynccontextmanager
    async def user_content_clear_boundary(self) -> AsyncIterator[None]:
        """Drain admitted projections and reject work crossing a full clear."""
        self._clear_request_count += 1
        self._clear_generation += 1
        try:
            async with self._clear_barrier.exclusive():
                yield
        finally:
            self._clear_cutoff_started_at_ms = max(
                self._clear_cutoff_started_at_ms,
                int(time.time() * 1000),
            )
            self._clear_request_count -= 1

    async def _on_span_completed(self, event: Event) -> None:
        if self._clear_request_count > 0 or not self._matches_current_memory_epoch(event):
            return
        try:
            payload = expect_payload(event, SpanCompleted)
        except PayloadTypeError:
            logger.exception("malformed SpanCompleted payload")
            return
        if (
            self._clear_cutoff_started_at_ms > 0
            and payload.started_at_ms <= self._clear_cutoff_started_at_ms
        ):
            return
        generation = self._clear_generation
        task = asyncio.create_task(self._serialized_project(payload, generation))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _serialized_project(self, p: SpanCompleted, generation: int) -> None:
        # Serialize per-subscriber so events that share span_id (e.g., the
        # base span row + a sub-table row published in sequence) project in
        # the order they were published.
        async with self._serialize_lock:
            async with self._clear_barrier.operation():
                if generation != self._clear_generation:
                    return
                await self._safe_project(p)

    def _matches_current_memory_epoch(self, event: Event) -> bool:
        if self._memory_epoch_getter is None:
            return True
        event_epoch = published_memory_epoch(event)
        if event_epoch is None:
            return True
        try:
            return event_epoch == int(self._memory_epoch_getter())
        except Exception:
            logger.exception("runtime_trace memory epoch resolution failed")
            return False

    async def _safe_project(self, p: SpanCompleted) -> None:
        try:
            await self._writer.project_span_completed(p)
        except Exception:
            logger.exception(
                "runtime_trace projection failed: span=%s node_type=%s",
                p.span_id,
                p.node_type,
            )
