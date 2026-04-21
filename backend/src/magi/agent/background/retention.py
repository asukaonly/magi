"""Periodic GC for background-task history retention.

Consumes ``agent.background_tasks.history_retention_days`` by hard-
deleting terminal rows older than the configured window together with
their event log entries. Only ``succeeded`` / ``failed`` / ``cancelled``
rows are eligible — active tasks are never touched.

The runner is idempotent, cancel-safe, and logs-only on failure so a
transient SQLite error cannot stop the dispatcher or the rest of the
runtime. Lifecycle drives ``start()`` / ``stop()`` alongside the task
manager.
"""

from __future__ import annotations

import asyncio
from typing import Callable

import structlog

from .store import BackgroundTaskStore

__all__ = ["BackgroundTaskRetentionGC"]


logger = structlog.get_logger(__name__)


_DEFAULT_INTERVAL_SECONDS = 3600.0


class BackgroundTaskRetentionGC:
    """Periodically purge expired background-task history."""

    def __init__(
        self,
        *,
        store: BackgroundTaskStore,
        retention_days: float,
        interval_seconds: float = _DEFAULT_INTERVAL_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._store = store
        self._retention_seconds = float(max(retention_days, 0.0)) * 86_400.0
        self._interval_seconds = float(max(interval_seconds, 1.0))
        self._clock = clock
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def enabled(self) -> bool:
        return self._retention_seconds > 0

    async def start(self) -> None:
        """Run an initial purge, then spawn the periodic loop."""
        if not self.enabled:
            logger.info("background task retention gc disabled")
            return
        if self._task is not None:
            return
        await self._purge_once()
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run_loop(), name="background-task-retention-gc"
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 - shutdown
            pass
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._interval_seconds
                )
                return  # stop requested while waiting
            except asyncio.TimeoutError:
                pass
            await self._purge_once()

    async def _purge_once(self) -> None:
        try:
            deleted = await self._store.purge_expired(
                retention_seconds=self._retention_seconds,
                now=self._clock() if self._clock is not None else None,
            )
        except Exception:  # noqa: BLE001 - GC is best-effort
            logger.exception("background task retention gc failed")
            return
        if deleted:
            logger.info(
                "background task retention gc removed tasks",
                count=deleted,
                retention_seconds=self._retention_seconds,
            )
