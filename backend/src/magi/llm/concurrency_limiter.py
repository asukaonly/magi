"""Shared concurrency limiter for LLM requests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar
from urllib.parse import urlparse

T = TypeVar("T")


@dataclass(slots=True)
class LLMConcurrencyStats:
    """Runtime stats for one concurrency bucket."""

    limit: int
    active: int
    waiting: int


@dataclass(slots=True)
class _LimiterState:
    semaphore: asyncio.Semaphore
    limit: int
    active: int = 0
    waiting: int = 0


class LLMConcurrencyLimiter:
    """Process-wide shared semaphore pool for LLM requests."""

    def __init__(self, *, default_limit: int = 1) -> None:
        if default_limit < 1:
            raise ValueError("default_limit must be at least 1")
        self._default_limit = int(default_limit)
        self._states: dict[str, _LimiterState] = {}

    @staticmethod
    def build_key(
        *,
        provider_name: str,
        model_name: str,
        request_family: str,
        base_url: str | None = None,
    ) -> str:
        provider = str(provider_name or "").strip().lower() or "unknown"
        model = str(model_name or "").strip().lower() or "unknown"
        family = str(request_family or "").strip().lower() or "chat"
        host = LLMConcurrencyLimiter._normalize_base_url_host(base_url) or provider
        return f"{provider}::{host}::{model}::{family}"

    @staticmethod
    def _normalize_base_url_host(base_url: str | None) -> str | None:
        if not base_url:
            return None

        raw_value = str(base_url).strip()
        if not raw_value:
            return None

        parsed = urlparse(raw_value)
        if not parsed.netloc and parsed.path and "://" not in raw_value:
            parsed = urlparse(f"//{raw_value}")

        host = (parsed.netloc or parsed.hostname or "").strip().lower()
        if not host:
            return None
        return host

    def get_stats(self, key: str) -> LLMConcurrencyStats:
        state = self._states.get(key)
        if state is None:
            return LLMConcurrencyStats(limit=self._default_limit, active=0, waiting=0)
        return LLMConcurrencyStats(limit=state.limit, active=state.active, waiting=state.waiting)

    async def run_with_limit(
        self,
        key: str,
        operation: Callable[[], Awaitable[T]],
        *,
        limit: int | None = None,
    ) -> T:
        """Run an awaitable factory while holding one permit for the key."""
        state = self._state_for(key, limit=limit)
        state.waiting += 1
        acquired = False
        try:
            await state.semaphore.acquire()
            acquired = True
            state.waiting -= 1
            state.active += 1
            try:
                return await operation()
            finally:
                state.active -= 1
                state.semaphore.release()
        finally:
            if not acquired:
                state.waiting -= 1

    def _state_for(self, key: str, *, limit: int | None = None) -> _LimiterState:
        effective_limit = int(limit) if limit is not None else self._default_limit
        if effective_limit < 1:
            raise ValueError("limit must be at least 1")

        state = self._states.get(key)
        if state is not None:
            return state

        state = _LimiterState(
            semaphore=asyncio.Semaphore(effective_limit),
            limit=effective_limit,
        )
        self._states[key] = state
        return state


_DEFAULT_LLM_CONCURRENCY_LIMITER: LLMConcurrencyLimiter | None = None


def get_llm_concurrency_limiter() -> LLMConcurrencyLimiter:
    """Return the process-wide shared concurrency limiter."""
    global _DEFAULT_LLM_CONCURRENCY_LIMITER
    if _DEFAULT_LLM_CONCURRENCY_LIMITER is None:
        _DEFAULT_LLM_CONCURRENCY_LIMITER = LLMConcurrencyLimiter()
    return _DEFAULT_LLM_CONCURRENCY_LIMITER
