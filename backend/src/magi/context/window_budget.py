"""Pure context-window budget policy shared by chat and agent execution."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from magi.llm.model_context import ModelContextProfile

FALLBACK_CONTEXT_WINDOW = 128_000
FALLBACK_OUTPUT_RESERVE = 8_192
SMALL_CONTEXT_WINDOW_LIMIT = 512_000
SMALL_CONTEXT_TRIGGER_RATIO = 0.75
LARGE_CONTEXT_TRIGGER_RATIO = 0.50
RECENT_TAIL_RATIO = 0.20
ASCII_CHARS_PER_TOKEN_ESTIMATE = 4.0
NON_ASCII_BYTES_PER_TOKEN_ESTIMATE = 2.5
GENERAL_SUMMARY_OUTPUT_RATIO = 0.05
PERSONA_SUMMARY_OUTPUT_RATIO = 0.02


@dataclass(frozen=True, slots=True)
class ContextWindowBudget:
    """Computed input, compaction, and retained-tail budgets for one model."""

    context_window: int
    output_reserve: int
    input_capacity: int
    compaction_trigger_tokens: int
    recent_tail_tokens: int
    uses_fallback: bool


@dataclass(frozen=True, slots=True)
class ContextWindowUsage:
    """Measured prompt usage against one model's context-window budget."""

    estimated_tokens: int
    compaction_trigger_tokens: int
    input_capacity: int

    @property
    def requires_compaction(self) -> bool:
        """Return whether the prompt crossed the early compaction threshold."""
        return self.estimated_tokens >= self.compaction_trigger_tokens

    @property
    def fits_input_capacity(self) -> bool:
        """Return whether the prompt can be sent with the output reserve intact."""
        return self.estimated_tokens <= self.input_capacity


@dataclass(frozen=True, slots=True)
class SummaryOutputProfile:
    """Purpose-specific bounds applied by the shared summary budget policy."""

    input_capacity_ratio: float
    min_tokens: int
    max_tokens: int


GENERAL_SUMMARY_OUTPUT_PROFILE = SummaryOutputProfile(
    input_capacity_ratio=GENERAL_SUMMARY_OUTPUT_RATIO,
    min_tokens=1_024,
    max_tokens=16_384,
)
PERSONA_SUMMARY_OUTPUT_PROFILE = SummaryOutputProfile(
    input_capacity_ratio=PERSONA_SUMMARY_OUTPUT_RATIO,
    min_tokens=512,
    max_tokens=4_096,
)


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


def resolve_summary_output_tokens(
    source_budget: ContextWindowBudget,
    summary_model_budget: ContextWindowBudget,
    *,
    profile: SummaryOutputProfile = GENERAL_SUMMARY_OUTPUT_PROFILE,
) -> int:
    """Size a summary for its destination, capped by the writer model."""
    capacity_target = int(source_budget.input_capacity * profile.input_capacity_ratio)
    profile_target = min(
        profile.max_tokens,
        max(profile.min_tokens, capacity_target),
    )
    return max(
        1,
        min(
            profile_target,
            source_budget.input_capacity,
            summary_model_budget.output_reserve,
        ),
    )


def estimate_text_tokens(text: str) -> int:
    """Return a lightweight multilingual token estimate for prompt text."""
    if not text:
        return 0
    ascii_chars = sum(1 for char in text if char.isascii())
    non_ascii_bytes = len(text.encode("utf-8", errors="replace")) - ascii_chars
    estimated = (
        ascii_chars / ASCII_CHARS_PER_TOKEN_ESTIMATE
        + non_ascii_bytes / NON_ASCII_BYTES_PER_TOKEN_ESTIMATE
    )
    return max(1, math.ceil(estimated))


def estimate_context_tokens(value: Any) -> int:
    """Return a provider-agnostic token estimate for structured prompt data."""
    try:
        rendered = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        rendered = str(value)
    return max(1, estimate_text_tokens(rendered))


def measure_context_window_usage(
    budget: ContextWindowBudget,
    value: Any,
    *,
    observed_input_tokens: int | None = None,
) -> ContextWindowUsage:
    """Measure a complete provider-facing prompt against its active model budget."""
    estimated_tokens = estimate_context_tokens(value)
    if observed_input_tokens is not None and observed_input_tokens > 0:
        estimated_tokens = max(estimated_tokens, observed_input_tokens)
    return ContextWindowUsage(
        estimated_tokens=estimated_tokens,
        compaction_trigger_tokens=budget.compaction_trigger_tokens,
        input_capacity=budget.input_capacity,
    )


__all__ = [
    "ContextWindowBudget",
    "ContextWindowUsage",
    "FALLBACK_CONTEXT_WINDOW",
    "build_context_window_budget",
    "estimate_context_tokens",
    "estimate_text_tokens",
    "measure_context_window_usage",
]
