"""Failure classification and retry helpers for function-calling execution."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ....llm.error_classifier import (
    ClassifiedError,
    LLMErrorKind,
    classify_exception,
    is_rate_limit_exception,
)
from ..task_budget import TaskBudgetExceeded

logger = logging.getLogger(__name__)


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
    """Classify execution failures and retry transient LLM rate limits."""

    _RATE_LIMIT_BACKOFF_SECONDS: tuple[float, ...]

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

    @staticmethod
    def _is_rate_limit_exception(exc: Exception) -> bool:
        """Shared detector for upstream 429 / rate-limit errors."""
        return bool(is_rate_limit_exception(exc))

    async def _invoke_with_rate_limit_backoff(
        self,
        factory: Callable[[], Awaitable[Any]],
        *,
        label: str,
    ) -> Any:
        """Run ``factory()`` with exponential backoff on rate-limit errors."""
        last_exc: Exception | None = None
        for attempt in range(len(self._RATE_LIMIT_BACKOFF_SECONDS) + 1):
            try:
                return await factory()
            except Exception as exc:  # noqa: BLE001 - transparent rethrow below
                if not self._is_rate_limit_exception(exc):
                    raise
                last_exc = exc
                if attempt >= len(self._RATE_LIMIT_BACKOFF_SECONDS):
                    logger.error(
                        "[FunctionCalling] %s rate-limited after %d retries, giving up",
                        label,
                        attempt,
                    )
                    raise
                delay = self._RATE_LIMIT_BACKOFF_SECONDS[attempt]
                logger.warning(
                    "[FunctionCalling] %s rate-limited; backing off %.1fs (attempt %d/%d)",
                    label,
                    delay,
                    attempt + 1,
                    len(self._RATE_LIMIT_BACKOFF_SECONDS),
                )
                await asyncio.sleep(delay)
        assert last_exc is not None
        raise last_exc
