"""Project SpanCompleted(node_type='llm_call') into the llm_usage table."""
from __future__ import annotations
import asyncio
import logging
from typing import Optional

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SpanCompleted
from magi.events.payload_helpers import expect_payload, PayloadTypeError
from magi.llm.usage_store import LLMUsageStore

logger = logging.getLogger(__name__)


class LLMUsageSubscriber:
    """Subscribe SpanCompleted; route llm_call → LLMUsageStore.record_call."""

    def __init__(self, *, event_bus, llm_usage_store: LLMUsageStore) -> None:
        self._bus = event_bus
        self._store = llm_usage_store
        self._sub_id: Optional[str] = None
        self._inflight: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._sub_id = await self._bus.subscribe(
            EventTypes.SPAN_COMPLETED, self._on_event,
        )

    async def stop(self) -> None:
        if self._sub_id is not None:
            try:
                await self._bus.unsubscribe(self._sub_id)
            except Exception:
                logger.exception("llm_usage_subscriber unsubscribe failed")
            self._sub_id = None
        await self.drain()

    async def drain(self) -> None:
        if not self._inflight:
            return
        await asyncio.gather(*list(self._inflight), return_exceptions=True)

    async def _on_event(self, event: Event) -> None:
        try:
            payload = expect_payload(event, SpanCompleted)
        except PayloadTypeError:
            return
        if payload.node_type != "llm_call":
            return
        task = asyncio.create_task(self._safe_record(event, payload))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _safe_record(self, event: Event, payload: SpanCompleted) -> None:
        try:
            attrs = payload.attributes or {}
            usage_payload = {
                "request_id": str(attrs.get("request_id") or payload.span_id),
                "provider": str(attrs.get("provider") or ""),
                "model": str(attrs.get("model") or payload.name),
                "request_kind": str(attrs.get("request_kind") or "unknown"),
                "prompt_tokens": int(attrs.get("prompt_tokens", 0)),
                "completion_tokens": int(attrs.get("completion_tokens", 0)),
                "total_tokens": int(attrs.get("total_tokens", 0)),
                "usage_available": bool(attrs.get("usage_available", False)),
                "latency_ms": int(payload.duration_ms),
                "ttft_ms": int(attrs.get("ttft_ms", 0)),
                "cost_usd": float(attrs.get("cost_usd", 0.0)),
                "success": (payload.status == "ok"),
                "error": payload.error.message if payload.error else None,
                "correlation_id": event.correlation_id or attrs.get("correlation_id"),
                "session_id": attrs.get("session_id"),
                "turn_id": payload.turn_id or attrs.get("turn_id"),
                "agent_id": attrs.get("agent_id"),
                "created_at": float(payload.started_at_ms) / 1000.0,
            }
            await self._store.record_call(usage_payload)
        except Exception:
            logger.exception("llm_usage projection failed: span=%s", payload.span_id)
