"""Helpers for publishing normalized LLM usage spans."""

from __future__ import annotations

import time
import uuid
from typing import Any


async def publish_llm_usage_span(
    *,
    provider: str,
    model: str,
    request_kind: str,
    success: bool,
    started_at: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    image_count: int = 0,
    usage_available: bool = False,
    error: str | None = None,
    event_context: dict[str, Any] | None = None,
) -> None:
    """Publish a ``SpanCompleted(node_type='llm_call')`` usage event."""
    from magi.events.domain_payloads import ToolError
    from magi.events.tracing import current_trace_context
    from magi.runtime_trace import enrich_event_context_with_turn_trace
    from magi.runtime_trace.span_publisher import publish_trace_span, resolve_event_bus

    context = enrich_event_context_with_turn_trace(event_context)
    ended_at = time.time()
    started_at_ms = int(started_at * 1000)
    ended_at_ms = int(ended_at * 1000)
    normalized_model = str(model or "unknown")
    normalized_provider = str(provider or "unknown")
    normalized_total_tokens = int(total_tokens or prompt_tokens + completion_tokens)
    ctx = current_trace_context()
    trace_id = ctx.trace_id if ctx is not None else str(context.get("trace_id") or "")
    parent_span_id = (
        ctx.span_id
        if ctx is not None
        else str(context.get("parent_span_id") or "").strip() or None
    )

    error_obj = ToolError(type="LLMError", message=str(error)[:1000]) if error else None

    await publish_trace_span(
        event_bus=resolve_event_bus(fallback=None),
        node_type="llm_call",
        name=normalized_model,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        status="ok" if success else "error",
        started_at_ms=started_at_ms,
        ended_at_ms=max(ended_at_ms, started_at_ms),
        error=error_obj,
        turn_id=context.get("turn_id"),
        attributes={
            "request_id": str(context.get("request_id") or uuid.uuid4().hex[:8]),
            "provider": normalized_provider,
            "model": normalized_model,
            "request_kind": str(request_kind or "unknown"),
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "input_tokens": int(prompt_tokens or 0),
            "output_tokens": int(completion_tokens or 0),
            "total_tokens": normalized_total_tokens,
            "image_count": int(image_count or 0),
            "usage_available": bool(usage_available),
            "correlation_id": context.get("correlation_id"),
            "session_id": context.get("session_id"),
            "turn_id": context.get("turn_id"),
            "agent_id": context.get("agent_id"),
        },
    )