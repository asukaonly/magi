"""Typed HTTP provider errors and retry metadata helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


class ProviderRateLimitError(RuntimeError):
    """Raised when a provider rejects a request with HTTP 429."""

    status_code = 429

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def parse_retry_after_seconds(
    value: str | None,
    *,
    now: datetime | None = None,
) -> float | None:
    """Parse Retry-After seconds or an HTTP date into a non-negative delay."""
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return max(0.0, float(normalized))
    except ValueError:
        pass

    try:
        deadline = parsedate_to_datetime(normalized)
    except (TypeError, ValueError, OverflowError):
        return None
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0.0, (deadline - current).total_seconds())


__all__ = ["ProviderRateLimitError", "parse_retry_after_seconds"]
