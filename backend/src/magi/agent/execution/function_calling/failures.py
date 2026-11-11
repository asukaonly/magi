"""Failure classification for function-calling execution."""

from __future__ import annotations

from ....llm.error_classifier import (
    ClassifiedError,
    LLMErrorKind,
    classify_exception,
)
from ..task_budget import TaskBudgetExceeded


# Mapping from the structured ``LLMErrorKind`` produced by
# ``classify_exception`` to the trace bucket strings consumed by
# function-calling execution traces. Anything unmapped falls back to
# ``EXECUTION_ERROR``.
_KIND_TO_TRACE_BUCKET: dict[LLMErrorKind, str] = {
    LLMErrorKind.RATE_LIMIT: "LLM_RATE_LIMIT",
    LLMErrorKind.TIMEOUT: "WORKER_TIMEOUT",
    LLMErrorKind.CONTENT_INSPECTION_FAILED: "CONTENT_INSPECTION_FAILED",
}


class FunctionCallingFailureMixin:
    """Classify execution failures for terminal outcomes and traces."""

    def _classify_exception_failure(self, exc: Exception) -> str:
        if isinstance(exc, TaskBudgetExceeded):
            return "TASK_BUDGET_EXCEEDED"
        classified: ClassifiedError = classify_exception(exc)
        return _KIND_TO_TRACE_BUCKET.get(classified.kind, "EXECUTION_ERROR")

    def _format_exception_trace_text(self, exc: Exception, *, max_length: int = 600) -> str:
        """Compose trace-visible error text that keeps the raw upstream message."""
        bucket = self._classify_exception_failure(exc)
        raw = str(exc).strip()
        if not raw:
            return bucket
        if len(raw) > max_length:
            raw = raw[: max_length - 1] + "..."
        return f"{bucket}: {raw}"
