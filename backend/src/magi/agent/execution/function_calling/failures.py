"""Failure classification and retry helpers for function-calling execution."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


class FunctionCallingFailureMixin:
    """Classify execution failures and retry transient LLM rate limits."""

    _RATE_LIMIT_BACKOFF_SECONDS: tuple[float, ...]

    def _classify_exception_failure(self, exc: Exception) -> str:
        message = str(exc).lower()
        if "datainspectionfailed" in message or "data_inspection_failed" in message:
            return "CONTENT_INSPECTION_FAILED"
        if "429" in message or "rate limit" in message.lower() or "速率限制" in message:
            return "LLM_RATE_LIMIT"
        if "timeout" in message:
            return "WORKER_TIMEOUT"
        return "EXECUTION_ERROR"

    def _format_exception_trace_text(self, exc: Exception, *, max_length: int = 600) -> str:
        """Compose trace-visible error text that keeps the raw upstream message."""
        bucket = self._classify_exception_failure(exc)
        raw = str(exc).strip()
        if not raw:
            return bucket
        if len(raw) > max_length:
            raw = raw[: max_length - 1] + "..."
        return f"{bucket}: {raw}"

    @classmethod
    def _is_rate_limit_exception(cls, exc: Exception) -> bool:
        """Shared detector for upstream 429 / rate-limit errors."""
        status_code = getattr(exc, "status_code", None)
        if status_code == 429:
            return True
        response = getattr(exc, "response", None)
        if getattr(response, "status_code", None) == 429:
            return True
        message = str(exc)
        lowered = message.lower()
        return (
            "429" in message
            or "rate limit" in lowered
            or "ratelimit" in lowered
            or "rate_limit" in lowered
            or "速率限制" in message
        )

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
