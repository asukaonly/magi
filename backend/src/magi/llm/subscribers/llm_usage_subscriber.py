"""Project SpanCompleted(node_type='llm_call') into the llm_usage table."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SpanCompleted
from magi.events.payload_helpers import expect_payload, PayloadTypeError
from magi.llm.pricing import (
    calculate_chat_cost,
    calculate_embedding_cost,
    calculate_image_generation_cost,
)
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
            EventTypes.SPAN_COMPLETED,
            self._on_event,
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
            usage_payload = self._build_usage_payload(event, payload, attrs)
            await self._store.record_call(usage_payload)

            observation_payload = self._build_cache_observation_payload(
                attrs,
                usage_payload,
            )
            if observation_payload is not None:
                await self._store.record_cache_observation(observation_payload)
        except Exception:
            logger.exception("llm_usage projection failed: span=%s", payload.span_id)

    def _build_usage_payload(
        self,
        event: Event,
        payload: SpanCompleted,
        attrs: dict[str, Any],
    ) -> dict[str, Any]:
        provider = str(attrs.get("provider") or "")
        model = str(attrs.get("model") or payload.name)
        prompt_tokens = int(attrs.get("prompt_tokens", 0))
        completion_tokens = int(attrs.get("completion_tokens", 0))
        cost_amount, cost_currency = self._resolve_cost(
            attrs=attrs,
            payload=payload,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return {
            "request_id": str(attrs.get("request_id") or payload.span_id),
            "provider": provider,
            "model": model,
            "request_kind": str(attrs.get("request_kind") or "unknown"),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": int(attrs.get("total_tokens", 0)),
            "cache_read_tokens": int(attrs.get("cache_read_tokens", 0)),
            "cache_write_tokens": int(attrs.get("cache_write_tokens", 0)),
            "cache_write_1h_tokens": int(attrs.get("cache_write_1h_tokens", 0)),
            "usage_available": bool(attrs.get("usage_available", False)),
            "latency_ms": int(payload.duration_ms),
            "ttft_ms": int(attrs.get("ttft_ms", 0)),
            "cost_usd": cost_amount,
            "cost_currency": cost_currency,
            "success": (payload.status == "ok"),
            "error": payload.error.message if payload.error else None,
            "correlation_id": event.correlation_id or attrs.get("correlation_id"),
            "session_id": attrs.get("session_id"),
            "turn_id": payload.turn_id or attrs.get("turn_id"),
            "agent_id": attrs.get("agent_id"),
            "created_at": float(payload.started_at_ms) / 1000.0,
        }

    def _resolve_cost(
        self,
        *,
        attrs: dict[str, Any],
        payload: SpanCompleted,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> tuple[float | None, str | None]:
        # Cost is recorded in the model's native billing currency. A None
        # amount/currency means "no pricing data" (distinct from a real 0),
        # which the stats UI renders as an em dash instead of a fake $0.00.
        explicit_cost = attrs.get("cost_usd")
        if explicit_cost is not None:
            return float(explicit_cost), "USD"

        provider_plan = str(attrs.get("provider_plan") or "").strip() or None
        cost_amount, cost_currency = calculate_chat_cost(
            provider=provider,
            provider_plan=provider_plan,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=int(attrs.get("cache_read_tokens", 0)),
            cache_write_tokens=int(attrs.get("cache_write_tokens", 0)),
            cache_write_1h_tokens=int(attrs.get("cache_write_1h_tokens", 0)),
        )
        if cost_amount is not None:
            return cost_amount, cost_currency
        return self._resolve_non_chat_cost(
            attrs=attrs,
            payload=payload,
            provider=provider,
            provider_plan=provider_plan,
            model=model,
            prompt_tokens=prompt_tokens,
        )

    def _resolve_non_chat_cost(
        self,
        *,
        attrs: dict[str, Any],
        payload: SpanCompleted,
        provider: str,
        provider_plan: str | None,
        model: str,
        prompt_tokens: int,
    ) -> tuple[float | None, str | None]:
        cost_amount, cost_currency = calculate_embedding_cost(
            provider=provider,
            provider_plan=provider_plan,
            model=model,
            prompt_tokens=prompt_tokens,
        )
        if cost_amount is not None:
            return cost_amount, cost_currency

        image_count = int(attrs.get("image_count", 0) or 0)
        if image_count <= 0:
            return None, None
        return calculate_image_generation_cost(
            provider=provider,
            provider_plan=provider_plan,
            model=str(attrs.get("model") or payload.name),
            image_count=image_count,
        )

    def _build_cache_observation_payload(
        self,
        attrs: dict[str, Any],
        usage_payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        cache_observation = attrs.get("cache_observation")
        if not isinstance(cache_observation, dict) or not cache_observation:
            return None
        return {
            **cache_observation,
            "request_id": usage_payload["request_id"],
            "provider": usage_payload["provider"],
            "model": usage_payload["model"],
            "request_kind": usage_payload["request_kind"],
            "session_id": usage_payload["session_id"],
            "turn_id": usage_payload["turn_id"],
            "agent_id": usage_payload["agent_id"],
            "cache_fields_seen": bool(attrs.get("cache_fields_seen", False)),
            "cache_read_tokens": usage_payload["cache_read_tokens"],
            "cache_write_tokens": usage_payload["cache_write_tokens"],
            "cache_write_1h_tokens": usage_payload["cache_write_1h_tokens"],
            "created_at": usage_payload["created_at"],
        }
