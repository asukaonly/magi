"""Subscribes to SpanCompleted and projects into runtime_trace tables.

Executable spans are written to trace_spans. Control records such as
turn_record update their owning table only, so UI trace trees stay focused on
execution structure instead of persistence bookkeeping.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SpanCompleted
from magi.events.payload_helpers import expect_payload, PayloadTypeError
from magi.runtime_trace.writer import RuntimeTraceWriter

logger = logging.getLogger(__name__)


class RuntimeTraceSubscriber:
    """Subscribe to SpanCompleted events; project into runtime_trace tables.

    trace_spans is written for executable events. Sub-tables (trace_tools,
    trace_llm_calls, trace_intent_resolutions, trace_turns) are written only
    when node_type matches the dispatch table. Handler errors are caught and
    logged so a single bad event cannot kill the subscription.
    """

    def __init__(self, *, event_bus, trace_store) -> None:
        self._bus = event_bus
        self._store = trace_store
        self._writer = RuntimeTraceWriter(trace_store)
        self._sub_id: Optional[str] = None
        self._inflight: set[asyncio.Task] = set()
        self._serialize_lock = asyncio.Lock()

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

    async def _on_span_completed(self, event: Event) -> None:
        try:
            payload = expect_payload(event, SpanCompleted)
        except PayloadTypeError:
            logger.exception("malformed SpanCompleted payload")
            return
        task = asyncio.create_task(self._serialized_project(payload))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _serialized_project(self, p: SpanCompleted) -> None:
        # Serialize per-subscriber so events that share span_id (e.g., the
        # base span row + a sub-table row published in sequence) project in
        # the order they were published.
        async with self._serialize_lock:
            await self._safe_project(p)

    async def _safe_project(self, p: SpanCompleted) -> None:
        try:
            await self._writer.project_span_completed(p)
        except Exception:
            logger.exception(
                "runtime_trace projection failed: span=%s node_type=%s",
                p.span_id,
                p.node_type,
            )
