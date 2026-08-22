"""Process-wide request pacing for rate-limited search providers."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable, Mapping

_DEFAULT_MIN_INTERVALS = {"brave": 1.0}


class SharedProviderRateLimiter:
    """Reserve provider request slots across tool and worker instances."""

    def __init__(
        self,
        min_intervals: Mapping[str, float] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._min_intervals = {
            str(name).strip().lower(): max(0.0, float(interval))
            for name, interval in (
                _DEFAULT_MIN_INTERVALS if min_intervals is None else min_intervals
            ).items()
        }
        self._clock = clock
        self._sleep = sleep
        self._next_allowed: dict[str, float] = {}
        self._lock = threading.Lock()

    async def wait(self, provider_name: str) -> None:
        """Wait until the caller's reserved request slot is available."""
        key = str(provider_name or "").strip().lower()
        interval = self._min_intervals.get(key, 0.0)
        if interval <= 0:
            return

        with self._lock:
            now = self._clock()
            reserved_at = max(now, self._next_allowed.get(key, now))
            self._next_allowed[key] = reserved_at + interval
        delay = reserved_at - now
        if delay > 0:
            await self._sleep(delay)

    def defer(self, provider_name: str, retry_after_seconds: float | None) -> None:
        """Push a provider's next slot out after a server rate-limit response."""
        if retry_after_seconds is None:
            return
        key = str(provider_name or "").strip().lower()
        delay = max(0.0, float(retry_after_seconds))
        with self._lock:
            deadline = self._clock() + delay
            self._next_allowed[key] = max(self._next_allowed.get(key, 0.0), deadline)


_SHARED_WEB_SEARCH_RATE_LIMITER = SharedProviderRateLimiter()


def get_web_search_rate_limiter() -> SharedProviderRateLimiter:
    """Return the process-wide web-search provider limiter."""
    return _SHARED_WEB_SEARCH_RATE_LIMITER


__all__ = ["SharedProviderRateLimiter", "get_web_search_rate_limiter"]
