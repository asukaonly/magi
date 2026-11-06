"""Interpret persisted projection diagnostics without guessing provider failures."""

from __future__ import annotations

import re
from typing import Literal

ProjectionFailureReason = Literal[
    "auth", "rate_limit", "timeout", "service_unavailable", "content_filter",
    "invalid_parameter", "content_inspection_failed", "model_unavailable",
    "invalid_response", "interrupted", "missing_source", "unknown",
]

_PROVIDER_REASON = re.compile(
    r"^L2 LLM call failed for .+ \(kind=(auth|rate_limit|timeout|service_unavailable|"
    r"content_filter|invalid_parameter|content_inspection_failed|unknown),"
)


def projection_failure_reason(error: str | None) -> str:
    """Recognize only diagnostics emitted by the owning projection pipeline."""
    text = error or ""
    provider = _PROVIDER_REASON.match(text)
    if provider:
        return provider.group(1)
    if text.startswith("No L2 LLM adapter is available for "):
        return "model_unavailable"
    if text.startswith("L2 LLM response is not "):
        return "invalid_response"
    if text in {
        "projection_attempt_budget_exhausted_on_startup", "projection_attempt_stale",
    }:
        return "interrupted"
    if text == "l1_event_not_found":
        return "missing_source"
    return "unknown"
