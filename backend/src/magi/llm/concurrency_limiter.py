"""Shared concurrency limiter for LLM requests."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import IntEnum
from typing import AsyncIterator, Awaitable, Callable, TypeVar
from urllib.parse import urlparse

T = TypeVar("T")


class LLMRequestPriority(IntEnum):
    """Priority class for model-capacity scheduling."""

    HIGH = 0
    MEDIUM = 1
    LOW = 2

    @classmethod
    def coerce(cls, value: "LLMRequestPriority | str | int | None") -> "LLMRequestPriority":
        if value is None:
            return cls.HIGH
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"high", "foreground", "interactive"}:
                return cls.HIGH
            if normalized in {"medium", "normal", "manual"}:
                return cls.MEDIUM
            if normalized in {"low", "background", "maintenance"}:
                return cls.LOW
        return cls(int(value))


@dataclass(slots=True)
class LLMConcurrencyStats:
    """Runtime stats for one concurrency bucket."""

    limit: int
    active: int
    waiting: int


@dataclass(slots=True)
class _LimiterState:
    condition: asyncio.Condition
    limit: int
    active: int = 0
    waiting: int = 0
    active_by_priority: dict[LLMRequestPriority, int] = field(default_factory=dict)
    waiting_by_priority: dict[LLMRequestPriority, int] = field(default_factory=dict)


class LLMConcurrencyLimiter:
    """Process-wide shared semaphore pool for LLM requests."""

    def __init__(
        self,
        *,
        default_limit: int = 1,
        high_priority_reserved_slots: int = 1,
    ) -> None:
        if default_limit < 1:
            raise ValueError("default_limit must be at least 1")
        if high_priority_reserved_slots < 0:
            raise ValueError("high_priority_reserved_slots must be non-negative")
        self._default_limit = int(default_limit)
        self._high_priority_reserved_slots = int(high_priority_reserved_slots)
        self._states: dict[str, _LimiterState] = {}

    @staticmethod
    def build_key(
        *,
        provider_name: str,
        model_name: str,
        request_family: str,
        base_url: str | None = None,
        provider_instance_id: str | None = None,
        provider_plan: str | None = None,
    ) -> str:
        provider = str(provider_name or "").strip().lower() or "unknown"
        provider_instance = (
            str(provider_instance_id or "").strip().lower() or provider
        )
        plan = str(provider_plan or "").strip().lower() or "api"
        model = str(model_name or "").strip().lower() or "unknown"
        family = str(request_family or "").strip().lower() or "chat"
        host = LLMConcurrencyLimiter._normalize_base_url_host(base_url) or provider
        return f"{provider}::{provider_instance}::{plan}::{host}::{model}::{family}"

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
        priority: LLMRequestPriority | str | int | None = None,
    ) -> T:
        """Run an awaitable factory while holding one permit for the key."""
        async with self.limit(key, limit=limit, priority=priority):
            return await operation()

    @asynccontextmanager
    async def limit(
        self,
        key: str,
        *,
        limit: int | None = None,
        priority: LLMRequestPriority | str | int | None = None,
    ) -> AsyncIterator[None]:
        """Hold one model-capacity permit for the duration of a block."""
        state = self._state_for(key, limit=limit)
        request_priority = LLMRequestPriority.coerce(priority)
        await self._acquire_slot(state, request_priority, limit=limit)
        try:
            yield
        finally:
            await self._release_slot(state, request_priority)

    async def _acquire_slot(
        self,
        state: _LimiterState,
        request_priority: LLMRequestPriority,
        *,
        limit: int | None,
    ) -> None:
        async with state.condition:
            self._maybe_update_limit(state, limit)
            state.waiting += 1
            self._increment(state.waiting_by_priority, request_priority)
            acquired = False
            try:
                while not self._can_acquire(state, request_priority):
                    await state.condition.wait()
                state.waiting -= 1
                self._decrement(state.waiting_by_priority, request_priority)
                state.active += 1
                self._increment(state.active_by_priority, request_priority)
                acquired = True
            except asyncio.CancelledError:
                if not acquired:
                    state.waiting -= 1
                    self._decrement(state.waiting_by_priority, request_priority)
                state.condition.notify_all()
                raise
            except Exception:
                if not acquired:
                    state.waiting -= 1
                    self._decrement(state.waiting_by_priority, request_priority)
                state.condition.notify_all()
                raise

    async def _release_slot(
        self,
        state: _LimiterState,
        request_priority: LLMRequestPriority,
    ) -> None:
        async with state.condition:
            state.active -= 1
            self._decrement(state.active_by_priority, request_priority)
            state.condition.notify_all()

    def _can_acquire(self, state: _LimiterState, priority: LLMRequestPriority) -> bool:
        if state.active >= state.limit:
            return False
        if self._has_higher_priority_waiter(state, priority):
            return False
        if priority is LLMRequestPriority.HIGH:
            return True

        lower_priority_active = sum(
            count
            for active_priority, count in state.active_by_priority.items()
            if active_priority is not LLMRequestPriority.HIGH
        )
        lower_priority_limit = max(1, state.limit - self._high_priority_reserved_slots)
        return lower_priority_active < lower_priority_limit

    @staticmethod
    def _has_higher_priority_waiter(
        state: _LimiterState,
        priority: LLMRequestPriority,
    ) -> bool:
        return any(
            waiting_priority < priority and count > 0
            for waiting_priority, count in state.waiting_by_priority.items()
        )

    @staticmethod
    def _increment(bucket: dict[LLMRequestPriority, int], priority: LLMRequestPriority) -> None:
        bucket[priority] = bucket.get(priority, 0) + 1

    @staticmethod
    def _decrement(bucket: dict[LLMRequestPriority, int], priority: LLMRequestPriority) -> None:
        next_count = bucket.get(priority, 0) - 1
        if next_count <= 0:
            bucket.pop(priority, None)
            return
        bucket[priority] = next_count

    def _state_for(self, key: str, *, limit: int | None = None) -> _LimiterState:
        effective_limit = int(limit) if limit is not None else self._default_limit
        if effective_limit < 1:
            raise ValueError("limit must be at least 1")

        state = self._states.get(key)
        if state is not None:
            return state

        state = _LimiterState(
            condition=asyncio.Condition(),
            limit=effective_limit,
        )
        self._states[key] = state
        return state

    def _maybe_update_limit(self, state: _LimiterState, new_limit: int | None) -> None:
        if new_limit is None:
            return

        effective_limit = int(new_limit)
        if effective_limit < 1:
            raise ValueError("limit must be at least 1")

        if effective_limit == state.limit:
            return

        state.limit = effective_limit
        state.condition.notify_all()


_DEFAULT_LLM_CONCURRENCY_LIMITER: LLMConcurrencyLimiter | None = None


def get_llm_concurrency_limiter() -> LLMConcurrencyLimiter:
    """Return the process-wide shared concurrency limiter."""
    global _DEFAULT_LLM_CONCURRENCY_LIMITER
    if _DEFAULT_LLM_CONCURRENCY_LIMITER is None:
        _DEFAULT_LLM_CONCURRENCY_LIMITER = LLMConcurrencyLimiter()
    return _DEFAULT_LLM_CONCURRENCY_LIMITER
