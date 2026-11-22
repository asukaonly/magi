"""Daily token budget circuit breaker for background LLM tasks.

Foreground user interactions (chat, interactive tool runs, online memory_query)
are never blocked by this guard. Only background automation jobs (L2 extraction,
L3 summaries, persona reflection, portrait/diary/watch jobs) are subject to the
optional daily token cap and smoothly defer until the next local calendar day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import time
from typing import Any

from ..config import get_config
from ..core.logger import get_logger
from .usage_store import LLMUsageStore, get_llm_usage_store

logger = get_logger(__name__)

BACKGROUND_REQUEST_KIND_PREFIXES: tuple[str, ...] = (
    "memory:l2_",
    "memory:l3_",
    "memory:temporal_",
    "memory:topic_",
    "memory:episodic_",
    "memory:l4_",
    "personality:journal_",
    "personality:reflection_",
    "timeline:diary_",
    "timeline_diary_",
    "user_profile:portrait_",
    "attention_watch:",
    "personal_tasks:watch",
    "background:",
)

_FOREGROUND_EXACT_PREFIXES: tuple[str, ...] = (
    "chat:",
    "agent:",
    "memory:hybrid_",
    "memory:grounding_filter",
    "memory:assertion_semantic",
    "provider_test",
    "config_provider_test",
)


def is_background_request_kind(request_kind: str | None) -> bool:
    """Return whether ``request_kind`` represents a non-interactive background job."""
    normalized = str(request_kind or "").strip().lower()
    if not normalized:
        return False
    if any(normalized.startswith(prefix) for prefix in _FOREGROUND_EXACT_PREFIXES):
        return False
    return any(normalized.startswith(prefix) for prefix in BACKGROUND_REQUEST_KIND_PREFIXES)


def _local_day_window(now: float) -> tuple[str, float, float]:
    dt = datetime.fromtimestamp(now)
    start_dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    next_dt = start_dt + timedelta(days=1)
    return start_dt.strftime("%Y-%m-%d"), start_dt.timestamp(), next_dt.timestamp()


@dataclass(frozen=True, slots=True)
class BackgroundBudgetDecision:
    """Outcome of one daily background token budget check."""

    allowed: bool
    used_tokens: int
    budget_tokens: int
    reset_at: float
    reason: str | None = None
    request_kind: str | None = None


class BackgroundBudgetExceededError(RuntimeError):
    """Raised when a background LLM job exceeds the daily token budget."""

    retryable = True

    def __init__(self, decision: BackgroundBudgetDecision) -> None:
        self.decision = decision
        super().__init__(
            f"Background LLM daily token budget exceeded for {decision.request_kind or 'background'} "
            f"(used={decision.used_tokens}, budget={decision.budget_tokens})"
        )


class BackgroundLLMBudgetGuard:
    """Enforce the user-configured daily token cap for background LLM jobs."""

    def __init__(
        self,
        *,
        usage_store: LLMUsageStore | None = None,
        cache_ttl_seconds: float = 5.0,
    ) -> None:
        self._usage_store = usage_store
        self._cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self._cached_day: str | None = None
        self._cached_at: float = 0.0
        self._cached_tokens: int = 0

    def invalidate(self) -> None:
        """Invalidate the cached daily token count."""
        self._cached_day = None
        self._cached_at = 0.0

    def _resolve_store(self) -> LLMUsageStore | None:
        if self._usage_store is not None:
            return self._usage_store
        try:
            return get_llm_usage_store()
        except Exception:
            return None

    @staticmethod
    def _configured_budget() -> int:
        try:
            return int(get_config().agent.memory.background_llm_daily_token_budget or 0)
        except Exception:
            return 0

    async def get_today_background_tokens(self, *, now: float | None = None) -> int:
        current = float(now if now is not None else time.time())
        day_key, day_start, _reset_at = _local_day_window(current)
        if (
            self._cached_day == day_key
            and current >= self._cached_at
            and (current - self._cached_at) < self._cache_ttl_seconds
        ):
            return self._cached_tokens

        store = self._resolve_store()
        if store is None:
            return 0
        try:
            used = await store.get_tokens_since(
                since_ts=day_start,
                until_ts=current + 1.0,
                request_kind_prefixes=BACKGROUND_REQUEST_KIND_PREFIXES,
            )
        except Exception as exc:
            logger.debug("Background token usage lookup skipped", error=str(exc))
            return 0
        self._cached_day = day_key
        self._cached_at = current
        self._cached_tokens = int(used)
        return self._cached_tokens

    async def check(
        self,
        request_kind: str | None,
        *,
        now: float | None = None,
        budget_override: int | None = None,
    ) -> BackgroundBudgetDecision:
        """Check whether a call for ``request_kind`` fits inside today's budget."""
        current = float(now if now is not None else time.time())
        _day_key, _day_start, reset_at = _local_day_window(current)
        budget = (
            max(0, int(budget_override))
            if budget_override is not None
            else max(0, self._configured_budget())
        )
        if not is_background_request_kind(request_kind):
            return BackgroundBudgetDecision(
                allowed=True,
                used_tokens=0,
                budget_tokens=budget,
                reset_at=reset_at,
                reason=None,
                request_kind=request_kind,
            )
        if budget <= 0:
            return BackgroundBudgetDecision(
                allowed=True,
                used_tokens=0,
                budget_tokens=0,
                reset_at=reset_at,
                reason=None,
                request_kind=request_kind,
            )

        used_tokens = await self.get_today_background_tokens(now=current)
        if used_tokens >= budget:
            logger.warning(
                "Background LLM call deferred by daily token budget",
                request_kind=request_kind,
                used_tokens=used_tokens,
                budget_tokens=budget,
                reset_at=reset_at,
            )
            return BackgroundBudgetDecision(
                allowed=False,
                used_tokens=used_tokens,
                budget_tokens=budget,
                reset_at=reset_at,
                reason="daily_background_token_budget_exceeded",
                request_kind=request_kind,
            )
        return BackgroundBudgetDecision(
            allowed=True,
            used_tokens=used_tokens,
            budget_tokens=budget,
            reset_at=reset_at,
            reason=None,
            request_kind=request_kind,
        )

    async def status(
        self,
        *,
        now: float | None = None,
        budget_override: int | None = None,
    ) -> dict[str, Any]:
        """Return structured budget status for API and Usage UI display."""
        current = float(now if now is not None else time.time())
        _day_key, _day_start, reset_at = _local_day_window(current)
        budget = (
            max(0, int(budget_override))
            if budget_override is not None
            else max(0, self._configured_budget())
        )
        used_tokens = await self.get_today_background_tokens(now=current)
        return {
            "enabled": budget > 0,
            "budget_tokens": budget,
            "used_tokens": used_tokens,
            "exceeded": budget > 0 and used_tokens >= budget,
            "reset_at": reset_at,
        }


_budget_guard: BackgroundLLMBudgetGuard | None = None


def get_background_llm_budget_guard() -> BackgroundLLMBudgetGuard:
    """Return the shared process-level background LLM budget guard."""
    global _budget_guard
    if _budget_guard is None:
        _budget_guard = BackgroundLLMBudgetGuard()
    return _budget_guard


def set_background_llm_budget_guard(guard: BackgroundLLMBudgetGuard | None) -> None:
    """Replace or clear the shared background LLM budget guard (for tests)."""
    global _budget_guard
    _budget_guard = guard


__all__ = [
    "BACKGROUND_REQUEST_KIND_PREFIXES",
    "BackgroundBudgetDecision",
    "BackgroundBudgetExceededError",
    "BackgroundLLMBudgetGuard",
    "get_background_llm_budget_guard",
    "is_background_request_kind",
    "set_background_llm_budget_guard",
]
