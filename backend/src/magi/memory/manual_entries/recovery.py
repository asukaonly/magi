"""Startup and periodic recovery for durable manual-entry intents."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any

from ...core.logger import get_logger
from .locks import entry_mutation_lock
from .store import ManualEntryRecoveryIdentity
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
        self._memory = memory
        self._page_size = int(page_size)
        self._interval_seconds = float(interval_seconds)
        self._workflow = workflow or ManualEntryWorkflow(
            store=store,
            projector=projector,
            memory=memory,
        )
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._linked_retry_entry_ids: set[str] = set()
        self._verify_all_linked_on_next_pass = True

    async def start(self) -> ManualEntryRecoveryStats:
        """Run startup recovery before returning, then enable periodic retries."""
        if self._task is not None:
            raise RuntimeError("Manual-entry recovery is already running")
        stats = await self._recover_without_raising(verify_linked=True)
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

    async def recover_pending(
        self,
        *,
        verify_linked: bool = False,
    ) -> ManualEntryRecoveryStats:
        """Recover durable work plus exact linked checks that previously failed."""
        stats = ManualEntryRecoveryStats()
        retry_ids_at_start = set(self._linked_retry_entry_ids)
        processed_entry_ids: set[str] = set()
        after_entry_id: str | None = None
        while True:
            entries = await self._store.list_recovery_candidates(
                after_entry_id=after_entry_id,
                limit=self._page_size,
                include_linked=verify_linked,
            )
            if not entries:
                break

            after_entry_id = entries[-1].entry_id
            await self._recover_identity_page(
                entries,
                verify_linked=verify_linked,
                stats=stats,
                processed_entry_ids=processed_entry_ids,
            )

            if len(entries) < self._page_size:
                break

        exact_retry_ids = sorted(retry_ids_at_start - processed_entry_ids)
        for offset in range(0, len(exact_retry_ids), self._page_size):
            chunk = exact_retry_ids[offset : offset + self._page_size]
            entries = await self._store.get_recovery_candidates(chunk)
            found_ids = {entry.entry_id for entry in entries}
            for missing_entry_id in set(chunk) - found_ids:
                self._linked_retry_entry_ids.discard(missing_entry_id)
            await self._recover_identity_page(
                entries,
                verify_linked=True,
                stats=stats,
                processed_entry_ids=processed_entry_ids,
            )

        return stats

    async def _recover_identity_page(
        self,
        entries: list[ManualEntryRecoveryIdentity],
        *,
        verify_linked: bool,
        stats: ManualEntryRecoveryStats,
        processed_entry_ids: set[str],
    ) -> None:
        fresh_entries = [
            entry for entry in entries if entry.entry_id not in processed_entry_ids
        ]
        if not fresh_entries:
            return
        processed_entry_ids.update(entry.entry_id for entry in fresh_entries)
        stats.scanned += len(fresh_entries)

        durable_entries = [
            entry for entry in fresh_entries if self._identity_requires_recovery(entry)
        ]
        durable_entry_ids = {entry.entry_id for entry in durable_entries}
        for entry in durable_entries:
            await self._recover_one(
                entry,
                verify_linked=False,
                stats=stats,
            )

        if not verify_linked:
            skipped_entries = len(fresh_entries) - len(durable_entries)
            if skipped_entries:
                stats.skipped += skipped_entries
                for entry in fresh_entries:
                    if entry.entry_id not in durable_entry_ids:
                        self._linked_retry_entry_ids.discard(entry.entry_id)
            return
        linked_entries = [
            entry
            for entry in fresh_entries
            if entry.entry_id not in durable_entry_ids
            and str(entry.l1_event_id or "").strip()
        ]
        if not linked_entries:
            return

        event_ids = [str(entry.l1_event_id) for entry in linked_entries]
        try:
            active_states = await self._memory.l1.get_raw_event_active_states(
                event_ids
            )
        except Exception as exc:
            failed_entry_ids = {entry.entry_id for entry in linked_entries}
            self._linked_retry_entry_ids.update(failed_entry_ids)
            stats.failed += len(linked_entries)
            logger.warning(
                "Manual-entry linked projection batch check failed",
                entry_count=len(linked_entries),
                error=str(exc),
                exc_info=True,
            )
            return

        for entry in linked_entries:
            event_id = str(entry.l1_event_id)
            if active_states.get(event_id) is True:
                self._linked_retry_entry_ids.discard(entry.entry_id)
                stats.skipped += 1
                continue
            await self._recover_one(
                entry,
                verify_linked=True,
                stats=stats,
            )

    async def _recover_one(
        self,
        identity: ManualEntryRecoveryIdentity,
        *,
        verify_linked: bool,
        stats: ManualEntryRecoveryStats,
    ) -> None:
        async with entry_mutation_lock(identity.entry_id):
            try:
                current = await self._store.get(identity.entry_id)
                if current is None or current.deleted_at is not None or (
                    not verify_linked and not projection_recovery_required(current)
                ):
                    self._linked_retry_entry_ids.discard(identity.entry_id)
                    stats.skipped += 1
                    return
                recovered = await self._workflow.recover_entry(current)
            except Exception as exc:
                self._linked_retry_entry_ids.add(identity.entry_id)
                stats.failed += 1
                logger.warning(
                    "Manual-entry recovery item failed",
                    entry_id=identity.entry_id,
                    error=str(exc),
                    exc_info=True,
                )
                return

        self._linked_retry_entry_ids.discard(identity.entry_id)
        if recovered:
            stats.recovered += 1
        else:
            stats.skipped += 1

    @staticmethod
    def _identity_requires_recovery(
        identity: ManualEntryRecoveryIdentity,
    ) -> bool:
        return bool(
            identity.delete_requested_at is not None
            or str(identity.pending_l1_event_id or "").strip()
            or not str(identity.l1_event_id or "").strip()
        )

    async def _recover_without_raising(
        self,
        *,
        verify_linked: bool = False,
    ) -> ManualEntryRecoveryStats:
        if verify_linked:
            self._verify_all_linked_on_next_pass = True
        try:
            stats = await self.recover_pending(verify_linked=verify_linked)
        except Exception as exc:
            logger.warning(
                "Manual-entry recovery scan failed",
                error=str(exc),
                exc_info=True,
            )
            return ManualEntryRecoveryStats(failed=1)
        if verify_linked:
            self._verify_all_linked_on_next_pass = False
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
                await self._recover_without_raising(
                    verify_linked=self._verify_all_linked_on_next_pass,
                )
            except asyncio.CancelledError:
                raise


__all__ = [
    "DEFAULT_RECOVERY_INTERVAL_SECONDS",
    "DEFAULT_RECOVERY_PAGE_SIZE",
    "ManualEntryRecoveryService",
    "ManualEntryRecoveryStats",
]
