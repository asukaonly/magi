"""Pure context-window budget policy shared by chat and agent execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from magi.llm.model_context import ModelContextProfile

FALLBACK_CONTEXT_WINDOW = 128_000
FALLBACK_OUTPUT_RESERVE = 8_192
SMALL_CONTEXT_WINDOW_LIMIT = 512_000
SMALL_CONTEXT_TRIGGER_RATIO = 0.75
LARGE_CONTEXT_TRIGGER_RATIO = 0.50
RECENT_TAIL_RATIO = 0.20
CHARS_PER_TOKEN_ESTIMATE = 4


@dataclass(frozen=True, slots=True)
class ContextWindowBudget:
    """Computed input, compaction, and retained-tail budgets for one model."""

    context_window: int
    output_reserve: int
    input_capacity: int
    compaction_trigger_tokens: int
    recent_tail_tokens: int
    uses_fallback: bool


def build_context_window_budget(profile: ModelContextProfile) -> ContextWindowBudget:
    """Build the context policy from the model that will receive the request."""
    configured_window = profile.context_window
    uses_fallback = configured_window is None or configured_window <= 0
    context_window = FALLBACK_CONTEXT_WINDOW if uses_fallback else configured_window

    configured_output = profile.max_output_tokens
    output_reserve = (
        configured_output
        if configured_output is not None and configured_output > 0
        else FALLBACK_OUTPUT_RESERVE
    )
    output_reserve = min(output_reserve, max(0, context_window - 1))
    input_capacity = max(1, context_window - output_reserve)
    trigger_ratio = (
        SMALL_CONTEXT_TRIGGER_RATIO
        if context_window < SMALL_CONTEXT_WINDOW_LIMIT
        else LARGE_CONTEXT_TRIGGER_RATIO
    )
    compaction_trigger_tokens = max(1, int(input_capacity * trigger_ratio))
    recent_tail_tokens = max(1, int(compaction_trigger_tokens * RECENT_TAIL_RATIO))
    return ContextWindowBudget(
        context_window=context_window,
        output_reserve=output_reserve,
        input_capacity=input_capacity,
        compaction_trigger_tokens=compaction_trigger_tokens,
        recent_tail_tokens=recent_tail_tokens,
        uses_fallback=uses_fallback,
    )


def estimate_context_tokens(value: Any) -> int:
    """Return a provider-agnostic token estimate for structured prompt data."""
    try:
        rendered = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        rendered = str(value)
    return max(1, len(rendered) // CHARS_PER_TOKEN_ESTIMATE)


__all__ = [
    "ContextWindowBudget",
    "FALLBACK_CONTEXT_WINDOW",
    "build_context_window_budget",
    "estimate_context_tokens",
]
