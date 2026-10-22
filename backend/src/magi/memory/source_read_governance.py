"""Apply durable memory boundaries to transient source evidence without ingesting it."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.sqlite import sqlite_connection_async
from .clear_generation import current_memory_clear_state
from .source_event_governance import business_source_references, source_event_tombstone_ids, matching_time_range_forget_barriers


@dataclass(frozen=True)
class ReadBoundary:
    epoch: int
    generation: int
    cutoff_at: float
    forget_signature: tuple[int, float]


class SourceReadGovernance:
    def __init__(self, memory: Any) -> None:
        self.memory = memory

    async def capture(self) -> ReadBoundary:
        async with self.memory.memory_operation_guard():
            generation, cutoff = await current_memory_clear_state(str(self.memory.memory_db_path))
            async with sqlite_connection_async(self.memory.memory_db_path) as db:
                rows = await db.execute_fetchall(
                    "SELECT COUNT(*), COALESCE(MAX(updated_at), 0) FROM memory_forget_operations"
                )
            return ReadBoundary(self.memory.memory_operation_epoch(), generation, cutoff,
                                (int(rows[0][0]), float(rows[0][1])))

    async def unchanged(self, boundary: ReadBoundary) -> bool:
        current = await self.capture()
        return current == boundary

    async def visible(
        self, boundary: ReadBoundary, *, source_type: str, source_item_id: str,
        occurred_at: float | None, event_ids: list[str],
    ) -> bool:
        if not await self.unchanged(boundary):
            return False
        if boundary.generation and (occurred_at is None or occurred_at <= boundary.cutoff_at):
            return False
        refs = [*event_ids, *business_source_references(
            source=source_type, event_type="SOURCE_EVENT", source_item_id=source_item_id,
        )]
        async with sqlite_connection_async(self.memory.memory_db_path) as db:
            if await source_event_tombstone_ids(db, refs):
                return False
            if occurred_at is None:
                rows = await db.execute_fetchall("SELECT 1 FROM memory_time_range_forget_barriers LIMIT 1")
                if rows:
                    return False
            elif await matching_time_range_forget_barriers(db, observed_from=occurred_at):
                return False
        if event_ids:
            from .hybrid_retrieval.correction_evidence_governance import decide_l1_correction_evidence
            decision = await decide_l1_correction_evidence(self.memory.l2, event_ids)
            if decision.drop_all or decision.blocked_event_ids:
                return False
        return True
