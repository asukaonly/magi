"""Result shaping for function-calling LLM calls."""

from __future__ import annotations

from typing import Any, Protocol

from ....config.models import ThinkingDepth
from .types import ToolCall


class ContextCompactorProtocol(Protocol):
    def record_input_tokens(self, tokens: int) -> None: ...

    def get_usage(self) -> dict[str, Any] | None: ...


def build_llm_trace(
    *,
    metadata: dict[str, Any] | None,
    thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
    duration_ms: int,
    model_name: str,
    provider_name: str,
) -> dict[str, Any]:
    trace_metrics = dict((metadata or {}).get("trace_metrics") or {})
    trace_metrics.setdefault("provider", provider_name)
    trace_metrics.setdefault("model", model_name)
    trace_metrics.setdefault("input_tokens", 0)
    trace_metrics.setdefault("output_tokens", 0)
    trace_metrics.setdefault("total_tokens", 0)
    trace_metrics.setdefault("reasoning_tokens", 0)
    trace_metrics.setdefault("cache_read_tokens", 0)
    trace_metrics.setdefault("cache_write_tokens", 0)
    trace_metrics.setdefault(
        "thinking_enabled",
        thinking_depth not in (ThinkingDepth.NONE, ThinkingDepth.LOW),
    )
    trace_metrics.setdefault("thinking_depth", thinking_depth.value)
    trace_metrics.setdefault("duration_ms", duration_ms)
    return trace_metrics


def build_llm_response_payload(
    *,
    provider_response: Any | None,
    content: str,
    streamed: bool,
    context_compactor: ContextCompactorProtocol,
    thinking_depth: ThinkingDepth,
    duration_ms: int,
    model_name: str,
    provider_name: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {"content": content}
    result["llm_trace"] = build_llm_trace(
        metadata=provider_response.metadata if provider_response is not None else None,
        thinking_depth=thinking_depth,
        duration_ms=duration_ms,
        model_name=model_name,
        provider_name=provider_name,
    )
    context_compactor.record_input_tokens(int(result["llm_trace"].get("input_tokens") or 0))
    context_usage = context_compactor.get_usage()
    if context_usage is not None:
        result["context_usage"] = {
            **context_usage,
            "measurement": "actual",
            "model_provider": provider_name,
            "model_id": model_name,
        }
    if provider_response is not None and provider_response.assistant_message:
        result["assistant_message"] = provider_response.assistant_message
    if provider_response is not None and provider_response.tool_calls:
        result["tool_calls"] = [
            ToolCall(
                id=tool_call.id,
                name=tool_call.name,
                arguments=tool_call.arguments,
            )
            for tool_call in provider_response.tool_calls
        ]
    if streamed:
        result["streamed"] = True
    return result


__all__ = [
    "ContextCompactorProtocol",
    "build_llm_response_payload",
    "build_llm_trace",
]
