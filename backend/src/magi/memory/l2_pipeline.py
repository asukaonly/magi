"""Asynchronous queue workers for L2 cognition processing."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Optional

from .event_contracts import MemoryEvent
from .l2_cognition_store import L2CognitionStore


@dataclass(slots=True)
class L2PipelineStats:
    """Counters for the staged L2 background pipeline."""

    is_running: bool = False
    extract_enqueued: int = 0
    extract_completed: int = 0
    extract_failed: int = 0
    extract_skipped: int = 0
    reconcile_enqueued: int = 0
    reconcile_completed: int = 0
    reconcile_failed: int = 0
    snapshot_enqueued: int = 0
    snapshot_completed: int = 0
    snapshot_failed: int = 0
    relations_written: int = 0
    assertions_written: int = 0


class L2Pipeline:
    """Owns asynchronous L2 extraction and follow-up queues."""

    def __init__(self, cognition_store: Optional[L2CognitionStore]) -> None:
        self._cognition_store = cognition_store
        self._extract_queue: asyncio.Queue[MemoryEvent | None] = asyncio.Queue()
        self._reconcile_queue: asyncio.Queue[list[str] | None] = asyncio.Queue()
        self._snapshot_queue: asyncio.Queue[list[str] | None] = asyncio.Queue()
        self._extract_worker: asyncio.Task[None] | None = None
        self._reconcile_worker: asyncio.Task[None] | None = None
        self._snapshot_worker: asyncio.Task[None] | None = None
        self._stats = L2PipelineStats()

    async def start(self) -> None:
        if self._stats.is_running or self._cognition_store is None:
            return

        self._stats.is_running = True
        self._extract_worker = asyncio.create_task(self._run_extract_worker())
        self._reconcile_worker = asyncio.create_task(self._run_reconcile_worker())
        self._snapshot_worker = asyncio.create_task(self._run_snapshot_worker())

    async def shutdown(self) -> None:
        if not self._stats.is_running:
            return

        self._stats.is_running = False
        await self._extract_queue.put(None)
        await self._reconcile_queue.put(None)
        await self._snapshot_queue.put(None)

        for worker in (self._extract_worker, self._reconcile_worker, self._snapshot_worker):
            if worker is None:
                continue
            try:
                await worker
            except asyncio.CancelledError:
                pass

        self._extract_worker = None
        self._reconcile_worker = None
        self._snapshot_worker = None

    async def enqueue_event(self, event: MemoryEvent) -> bool:
        if self._cognition_store is None or not event.cognition_eligible:
            self._stats.extract_skipped += 1
            return False

        await self._extract_queue.put(event)
        self._stats.extract_enqueued += 1
        return True

    async def enqueue_entities(self, entity_ids: list[str]) -> bool:
        normalized = sorted({entity_id.strip() for entity_id in entity_ids if entity_id and entity_id.strip()})
        if not normalized or self._cognition_store is None:
            return False
        await self._reconcile_queue.put(normalized)
        self._stats.reconcile_enqueued += 1
        return True

    async def enqueue_snapshot_refresh(self, entity_ids: list[str]) -> bool:
        normalized = sorted({entity_id.strip() for entity_id in entity_ids if entity_id and entity_id.strip()})
        if not normalized or self._cognition_store is None:
            return False
        await self._snapshot_queue.put(normalized)
        self._stats.snapshot_enqueued += 1
        return True

    def get_statistics(self) -> dict[str, int | bool]:
        return asdict(self._stats)

    async def _run_extract_worker(self) -> None:
        if self._cognition_store is None:
            return

        while True:
            event = await self._extract_queue.get()
            try:
                if event is None:
                    break
                result = await self._cognition_store.apply_memory_event(event)
                self._stats.extract_completed += 1
                self._stats.relations_written += int(result["relation_count"])
                self._stats.assertions_written += int(result["assertion_count"])
            except Exception:
                self._stats.extract_failed += 1
            finally:
                self._extract_queue.task_done()

    async def _run_reconcile_worker(self) -> None:
        while True:
            entity_ids = await self._reconcile_queue.get()
            try:
                if entity_ids is None:
                    break
                self._stats.reconcile_completed += 1
            except Exception:
                self._stats.reconcile_failed += 1
            finally:
                self._reconcile_queue.task_done()

    async def _run_snapshot_worker(self) -> None:
        while True:
            entity_ids = await self._snapshot_queue.get()
            try:
                if entity_ids is None:
                    break
                self._stats.snapshot_completed += 1
            except Exception:
                self._stats.snapshot_failed += 1
            finally:
                self._snapshot_queue.task_done()


__all__ = ["L2Pipeline", "L2PipelineStats"]
