"""Debounced refresh scheduling for product-facing user portrait projections."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .portrait_projection_builder import UserPortraitProjectionBuilder
from .portrait_projection_repository import UserPortraitProjectionRepository
from .projection_repository import UserProfileProjectionRepository

logger = logging.getLogger(__name__)

DEFAULT_PORTRAIT_REFRESH_DELAY_SECONDS = 120.0

RefreshCallback = Callable[[str], Awaitable[None]]
SleepCallback = Callable[[float], Awaitable[None]]
DelaySeconds = float | Callable[[], float]


class UserPortraitProjectionScheduler:
    """Coalesce assertion-driven portrait refresh requests per user."""

    def __init__(
        self,
        *,
        refresh_callback: RefreshCallback,
        delay_seconds: DelaySeconds = DEFAULT_PORTRAIT_REFRESH_DELAY_SECONDS,
        sleep: SleepCallback = asyncio.sleep,
    ) -> None:
        self._refresh_callback = refresh_callback
        self._delay_seconds = delay_seconds
        self._sleep = sleep
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def schedule_assertion_change(self, assertion: Any) -> None:
        """Schedule a refresh when the changed assertion belongs to a local user."""
        user_id = _user_id_from_assertion(assertion)
        if user_id is None:
            return
        await self.schedule_user(user_id)

    async def schedule_user(self, user_id: str) -> None:
        """Schedule or replace the delayed refresh for one user."""
        clean_user_id = str(user_id or "").strip()
        if not clean_user_id:
            return
        delay = max(0.0, self._current_delay_seconds())
        async with self._lock:
            existing = self._tasks.get(clean_user_id)
            if existing is not None and not existing.done():
                existing.cancel()
            self._tasks[clean_user_id] = asyncio.create_task(
                self._run_after_delay(clean_user_id, delay),
            )

    async def wait_idle(self) -> None:
        """Wait until all currently queued refreshes finish."""
        while True:
            async with self._lock:
                tasks = [task for task in self._tasks.values() if not task.done()]
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown(self) -> None:
        """Cancel pending refreshes during runtime shutdown."""
        async with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_after_delay(self, user_id: str, delay_seconds: float) -> None:
        current_task = asyncio.current_task()
        try:
            if delay_seconds > 0:
                await self._sleep(delay_seconds)
            await self._refresh_callback(user_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            logger.warning(
                "User portrait projection refresh failed",
                extra={"user_id": user_id, "error": str(exc)},
            )
        finally:
            async with self._lock:
                if current_task is not None and self._tasks.get(user_id) is current_task:
                    self._tasks.pop(user_id, None)

    def _current_delay_seconds(self) -> float:
        value = self._delay_seconds() if callable(self._delay_seconds) else self._delay_seconds
        try:
            return float(value)
        except (TypeError, ValueError):
            return DEFAULT_PORTRAIT_REFRESH_DELAY_SECONDS


async def schedule_portrait_projection_refresh_after_assertion_change(
    unified_memory: Any,
    assertion: Any,
) -> None:
    """Schedule a debounced portrait projection refresh for a changed assertion."""
    scheduler = get_portrait_projection_scheduler(unified_memory)
    if scheduler is None:
        return
    await scheduler.schedule_assertion_change(assertion)


async def schedule_portrait_projection_refresh(
    unified_memory: Any,
    user_id: str,
) -> None:
    """Schedule a debounced portrait refresh for one known local user."""
    scheduler = get_portrait_projection_scheduler(unified_memory)
    if scheduler is None:
        return
    await scheduler.schedule_user(user_id)


def register_l2_portrait_projection_refresh(unified_memory: Any) -> None:
    """Attach portrait refresh scheduling to L2 assertion writes when available."""
    l2 = getattr(unified_memory, "l2", None)
    if l2 is None or not hasattr(l2, "set_assertion_change_callback"):
        return

    async def callback(assertion: Any) -> None:
        await schedule_portrait_projection_refresh_after_assertion_change(
            unified_memory,
            assertion,
        )

    l2.set_assertion_change_callback(callback)


def get_portrait_projection_scheduler(unified_memory: Any) -> UserPortraitProjectionScheduler | None:
    """Return the runtime scheduler for one unified memory instance."""
    if unified_memory is None:
        return None
    existing = getattr(unified_memory, "_portrait_projection_scheduler", None)
    if isinstance(existing, UserPortraitProjectionScheduler):
        return existing

    l2 = getattr(unified_memory, "l2", None)
    db_path = str(getattr(l2, "db_path", "") or "") if l2 is not None else ""
    if l2 is None or not db_path:
        return None

    async def refresh(user_id: str) -> None:
        profile_projection = None
        try:
            profile_projection = await UserProfileProjectionRepository(db_path).get(user_id)
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            logger.debug(
                "User portrait profile projection lookup failed",
                extra={"user_id": user_id, "error": str(exc)},
            )
        projection = await UserPortraitProjectionBuilder(
            l2,
            profile_projection=profile_projection,
        ).build(user_id)
        await UserPortraitProjectionRepository(db_path).upsert(projection)

    scheduler = UserPortraitProjectionScheduler(
        refresh_callback=refresh,
        delay_seconds=lambda: _configured_delay_seconds(unified_memory),
    )
    setattr(unified_memory, "_portrait_projection_scheduler", scheduler)
    return scheduler


def _configured_delay_seconds(unified_memory: Any) -> float:
    getter = getattr(unified_memory, "_memory_config_getter", None)
    if callable(getter):
        try:
            return float(
                getattr(
                    getattr(getter(), "l2", None),
                    "portrait_projection_refresh_delay_seconds",
                    DEFAULT_PORTRAIT_REFRESH_DELAY_SECONDS,
                )
            )
        except Exception:
            return DEFAULT_PORTRAIT_REFRESH_DELAY_SECONDS
    return DEFAULT_PORTRAIT_REFRESH_DELAY_SECONDS


def _user_id_from_assertion(assertion: Any) -> str | None:
    if not isinstance(assertion, dict):
        return None
    if str(assertion.get("entity_type") or "") != "user":
        return None
    entity_id = str(assertion.get("entity_id") or "")
    if not entity_id.startswith("user:"):
        return None
    user_id = entity_id.split(":", 1)[1].strip()
    return user_id or None


__all__ = [
    "DEFAULT_PORTRAIT_REFRESH_DELAY_SECONDS",
    "UserPortraitProjectionScheduler",
    "get_portrait_projection_scheduler",
    "register_l2_portrait_projection_refresh",
    "schedule_portrait_projection_refresh",
    "schedule_portrait_projection_refresh_after_assertion_change",
]
