"""Shared capacity-aware execution for cumulative context summaries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .window_budget import estimate_context_tokens


SUMMARY_INPUT_SAFETY_RATIO = 0.90
SUMMARY_MERGE_OUTPUT_RATIO = 0.40


class SummaryPromptTooLargeError(ValueError):
    """Raised when summary instructions leave no room for source text."""


@dataclass(frozen=True, slots=True)
class SummaryChunkRequest:
    """One provider-ready cumulative summary request."""

    index: int
    prompt: str
    source_chunk: str
    is_final: bool


SummaryPromptBuilder = Callable[[str, str], str]
SummaryChunkCaller = Callable[[SummaryChunkRequest], Awaitable[str]]


def resolve_cumulative_summary_output_tokens(
    requested_tokens: int,
    *,
    input_capacity: int,
) -> int:
    """Keep generated summaries small enough to fit into a later merge request."""

    merge_safe_limit = max(1, int(max(1, input_capacity) * SUMMARY_MERGE_OUTPUT_RATIO))
    return max(1, min(max(1, requested_tokens), merge_safe_limit))


async def generate_cumulative_summary(
    *,
    source_text: str,
    system_prompt: str,
    input_capacity: int,
    build_prompt: SummaryPromptBuilder,
    call_chunk: SummaryChunkCaller,
) -> str:
    """Summarize all source text without exceeding the writer model's input budget."""

    remaining = str(source_text or "").strip()
    if not remaining:
        return ""

    safe_input_limit = max(1, int(max(1, input_capacity) * SUMMARY_INPUT_SAFETY_RATIO))
    cumulative_summary = ""
    index = 0
    while remaining:
        chunk, remaining = _take_fitting_prefix(
            remaining,
            system_prompt=system_prompt,
            input_limit=safe_input_limit,
            build_prompt=lambda candidate: build_prompt(cumulative_summary, candidate),
        )
        prompt = build_prompt(cumulative_summary, chunk)
        generated = await call_chunk(
            SummaryChunkRequest(
                index=index,
                prompt=prompt,
                source_chunk=chunk,
                is_final=not remaining,
            )
        )
        cumulative_summary = str(generated or "").strip()
        if not cumulative_summary:
            return ""
        index += 1
    return cumulative_summary


def _take_fitting_prefix(
    text: str,
    *,
    system_prompt: str,
    input_limit: int,
    build_prompt: Callable[[str], str],
) -> tuple[str, str]:
    if _measure_summary_prompt(system_prompt, build_prompt(text)) <= input_limit:
        return text, ""

    low = 1
    high = len(text)
    best = 0
    while low <= high:
        midpoint = (low + high) // 2
        candidate = text[:midpoint]
        if _measure_summary_prompt(system_prompt, build_prompt(candidate)) <= input_limit:
            best = midpoint
            low = midpoint + 1
        else:
            high = midpoint - 1

    if best <= 0:
        base_tokens = _measure_summary_prompt(system_prompt, build_prompt(""))
        raise SummaryPromptTooLargeError(
            "Summary instructions and cumulative state leave no room for source text "
            f"(estimated={base_tokens}, input_limit={input_limit})."
        )

    split_at = _prefer_text_boundary(text, best)
    return text[:split_at], text[split_at:]


def _measure_summary_prompt(system_prompt: str, user_prompt: str) -> int:
    return estimate_context_tokens(
        {
            "system_prompt": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
    )


def _prefer_text_boundary(text: str, hard_limit: int) -> int:
    if hard_limit >= len(text):
        return len(text)
    minimum = max(1, int(hard_limit * 0.70))
    candidate = text[:hard_limit]
    for separator in ("\n\n", "\n", "。", "！", "？", ". ", "! ", "? ", " "):
        boundary = candidate.rfind(separator, minimum)
        if boundary >= minimum:
            return boundary + len(separator)
    return hard_limit


__all__ = [
    "SummaryChunkRequest",
    "SummaryPromptTooLargeError",
    "generate_cumulative_summary",
    "resolve_cumulative_summary_output_tokens",
]
