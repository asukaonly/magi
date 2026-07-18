"""Fail-closed write boundary for derived L1 projections."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from ..core.sqlite import sqlite_connection_async
from .event_contracts import MemoryEvent
from .source_event_governance import (
    govern_source_events_by_time_range,
    memory_event_source_references,
)


class UnifiedGovernedL1WriteMixin:
    """Serialize derived L1 writes with forget barriers and source governance."""

    l1: Any
    memory_db_path: str
    _clear_barrier: Any
    _write_lock: Any

    @asynccontextmanager
    async def governed_l1_write_guard(self) -> AsyncIterator[None]:
        """Serialize a source reservation with durable forget selection."""
        async with self._clear_barrier.operation():
            async with self._write_lock:
                yield

    async def governed_l1_event_rejection_reason(
        self,
        event: MemoryEvent,
    ) -> Literal["time_range", "source_reference"] | None:
        """Return the durable rule that would reject one derived L1 event."""
        async with self.governed_l1_write_guard():
            return await self.governed_l1_event_rejection_reason_guarded(event)

    async def store_governed_l1_event(self, event: MemoryEvent) -> str | None:
        """Persist a derived event, returning None when a forget barrier rejects it."""
        async with self._clear_barrier.operation():
            return await self._store_governed_l1_event_guarded(event)

    async def _store_governed_l1_event_guarded(self, event: MemoryEvent) -> str | None:
        if self.l1 is None:
            raise RuntimeError("L1 memory is unavailable for governed projection")
        async with self._write_lock:
            return await self.store_governed_l1_event_under_write_lock(event)

    async def governed_l1_event_rejection_reason_guarded(
        self,
        event: MemoryEvent,
    ) -> Literal["time_range", "source_reference"] | None:
        async with sqlite_connection_async(self.memory_db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                time_range_decision = await govern_source_events_by_time_range(
                    db,
                    event_ids=(event.event_id, event.turn_id),
                    observed_from=float(event.timestamp),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        if time_range_decision.delete_l1_event:
            return "time_range"
        if await self._any_source_reference_is_tombstoned(
            memory_event_source_references(event)
        ):
            return "source_reference"
        return None

    async def store_governed_l1_event_under_write_lock(
        self,
        event: MemoryEvent,
    ) -> str | None:
        """Store one event while the caller holds ``governed_l1_write_guard``."""
        if self.l1 is None:
            raise RuntimeError("L1 memory is unavailable for governed projection")
        rejection_reason = await self.governed_l1_event_rejection_reason_guarded(
            event
        )
        if rejection_reason is not None:
            return None
        return str(await self.l1.store(event))


__all__ = ["UnifiedGovernedL1WriteMixin"]
