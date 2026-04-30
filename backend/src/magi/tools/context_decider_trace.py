"""LLM trace helpers for ContextDecider."""

from __future__ import annotations

from typing import Any, Optional


class ContextDeciderTraceMixin:
    """Build trace metrics for context-decider LLM calls."""

    llm: Any

    def _build_llm_trace(
        self,
        *,
        metadata: Optional[dict[str, Any]],
        disable_thinking: bool,
        duration_ms: int,
    ) -> dict[str, Any]:
        trace_metrics = dict((metadata or {}).get("trace_metrics") or {})
        trace_metrics.setdefault("provider", getattr(self.llm, "provider_name", "unknown"))
        trace_metrics.setdefault("model", str(getattr(self.llm, "model_name", "unknown")))
        trace_metrics.setdefault("input_tokens", 0)
        trace_metrics.setdefault("output_tokens", 0)
        trace_metrics.setdefault("total_tokens", 0)
        trace_metrics.setdefault("reasoning_tokens", 0)
        trace_metrics.setdefault("cache_read_tokens", 0)
        trace_metrics.setdefault("cache_write_tokens", 0)
        trace_metrics.setdefault("thinking_enabled", not disable_thinking)
        trace_metrics.setdefault("duration_ms", duration_ms)
        return trace_metrics


__all__ = ["ContextDeciderTraceMixin"]
