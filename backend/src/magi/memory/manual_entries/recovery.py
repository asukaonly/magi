"""Startup and periodic recovery for durable manual-entry intents."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any

from ...core.logger import get_logger
from .locks import entry_mutation_lock
from .workflow import ManualEntryWorkflow, projection_recovery_required

logger = get_logger(__name__)

DEFAULT_RECOVERY_PAGE_SIZE = 100
DEFAULT_RECOVERY_INTERVAL_SECONDS = 60.0


@dataclass(slots=True)
class ManualEntryRecoveryStats:
    """Outcome of one bounded, paginated recovery pass."""

    scanned: int = 0
    recovered: int = 0
    failed: int = 0
    skipped: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class ManualEntryRecoveryService:
    """Recover incomplete projections and delete-gated entries."""

    def __init__(
        self,
        *,
        store: Any,
        projector: Any,
        memory: Any,
        page_size: int = DEFAULT_RECOVERY_PAGE_SIZE,
        interval_seconds: float = DEFAULT_RECOVERY_INTERVAL_SECONDS,
        workflow: ManualEntryWorkflow | None = None,
    ) -> None:
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        if interval_seconds < 0:
            raise ValueError("interval_seconds must not be negative")
        self._store = store
        self._page_size = int(page_size)
        self._interval_seconds = float(interval_seconds)
        self._workflow = workflow or ManualEntryWorkflow(
            store=store,
            projector=projector,
            memory=memory,
        )
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> ManualEntryRecoveryStats:
        """Run startup recovery before returning, then enable periodic retries."""
        if self._task is not None:
            raise RuntimeError("Manual-entry recovery is already running")
        stats = await self._recover_without_raising()
        if self._interval_seconds > 0:
            self._stopped.clear()
            self._task = asyncio.create_task(
                self._run_loop(),
                name="manual-entry-recovery",
            )
        return stats

    async def stop(self) -> None:
        """Stop the periodic retry loop."""
        self._stopped.set()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def recover_pending(self) -> ManualEntryRecoveryStats:
        """Scan every current recovery candidate exactly once this pass."""
        stats = ManualEntryRecoveryStats()
        after_entry_id: str | None = None
        while True:
            entries = await self._store.list_recovery_candidates(
                after_entry_id=after_entry_id,
                limit=self._page_size,
            )
            if not entries:
                break

            for snapshot in entries:
                after_entry_id = snapshot.entry_id
                stats.scanned += 1
                async with entry_mutation_lock(snapshot.entry_id):
                    try:
                        current = await self._store.get(snapshot.entry_id)
                        if current is None or not projection_recovery_required(current):
                            stats.skipped += 1
                            continue
                        await self._workflow.recover_entry(current)
                    except Exception as exc:
                        stats.failed += 1
                        logger.warning(
                            "Manual-entry recovery item failed",
                            entry_id=snapshot.entry_id,
                            error=str(exc),
                            exc_info=True,
                        )
                    else:
                        stats.recovered += 1

            if len(entries) < self._page_size:
                break

        return stats

    async def _recover_without_raising(self) -> ManualEntryRecoveryStats:
        try:
            stats = await self.recover_pending()
        except Exception as exc:
            logger.warning(
                "Manual-entry recovery scan failed",
                error=str(exc),
                exc_info=True,
            )
            return ManualEntryRecoveryStats(failed=1)
        logger.info("Manual-entry recovery pass completed", **stats.to_dict())
        return stats

    async def _run_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                await asyncio.wait_for(
                    self._stopped.wait(),
                    timeout=self._interval_seconds,
                )
            except asyncio.TimeoutError:
                await self._recover_without_raising()
            except asyncio.CancelledError:
                raise


__all__ = [
    "DEFAULT_RECOVERY_INTERVAL_SECONDS",
    "DEFAULT_RECOVERY_PAGE_SIZE",
    "ManualEntryRecoveryService",
    "ManualEntryRecoveryStats",
]
